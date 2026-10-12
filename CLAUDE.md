# Project rules: Trading Performance Analytics Pipeline

Portfolio project for student Data Analyst / Fintech applications. Plan: see the phased plan
(Phases 0-9) approved by the user.

## Rules (apply to the whole project)
- **Never read, print, list contents of, or commit anything in `data/private/`.** It holds the
  user's real trades. Parser work uses headers + 3 redacted sample rows the user pastes.
- **Do not start any phase without the user's explicit OK.** Plan approval is not phase approval.
  Stop at the end of each phase and wait.
- **Explain every decision briefly**, so the user can defend it in interviews.
- **After each phase, give 3 interview questions** the user should be able to answer.
- Small, meaningful commits per phase; run tests (`make test`, `make lint`) before each commit.
- Synthetic demo data must be realistic but contain NO planted edge.
- Public demo must not depend on yfinance (synthetic bars or small parquet sample).

## Contract multipliers (user trades NQ and MNQ; ES/MES also configured)
Source of truth is the config table in `src/trading_analytics/ingest/instruments.py`; unknown products fail loudly.
| Symbol | $ per point | Tick size | Tick value |
|--------|-------------|-----------|------------|
| NQ     | 20          | 0.25      | 5.00       |
| MNQ    | 2           | 0.25      | 0.50       |
| ES     | 50          | 0.25      | 12.50      |
| MES    | 5           | 0.25      | 1.25       |

## Stack
Python 3.12 (uv), DuckDB, dbt-duckdb, Streamlit, pytest, ruff, Docker, GitHub Actions.
Commands: `make setup | test | lint | guard | ingest | transform | dashboard | all`.

## Key decisions so far
- **Trade = flat-to-flat per (account, contract)** (matches Lucid). NQZ6 and MNQZ6 are separate
  positions; never netted. FIFO lots inside a trade; flips close at the zero crossing and the
  remainder opens a new trade (commissions split pro rata by quantity).
- **Open position at end of data is reported as unmatched**; no exit is ever invented.
- **`is_active=false` fills are excluded from pairing** and listed in the data quality report.
- **UTC only**: `_timestamp` is the source of truth. The display `Timestamp` (Israel local, shifts
  with DST) is ignored. `trade_date` is the platform's session date of the exit fill.
- **Gross vs net**: `gross_pnl`, `net_pnl = gross - fees - commissions` are separate columns.
  The platform's Net PnL is net; Avg Win / Avg Loss / PNL High-Low are gross. Win/loss
  classification is configurable (`win_loss_basis`), default gross.
- **Fees = 0, commission = per-fill total** (Tradovate export has no fees column).
- **Reconciliation**: `make reconcile` compares against gitignored `data/private/expected.yaml`
  (template: `docs/expected.example.yaml`). User runs it; Claude never reads those files and
  committed tests use synthetic fixtures only.
- **Demo data has no edge by construction** (`src/trading_analytics/demo/`): driftless price
  martingale, coin-flip direction, volatility-scaled stop/target, random timeouts, fixed-delay
  (non-look-ahead) scaling. Net P&L is negative only through commissions. Verified by permutation
  tests (`trading_analytics/stats.py`) incl. a seed-calibration test and a planted-edge power test.
- **Duration is not an actionable condition**: it is only known after the trade and is mechanically
  coupled to the outcome. Insights (Phase 8) must not present duration as a "when to trade" finding.
- **Real market bars (Phase 5, done before Phase 4)**: `make bars` (`scripts/daily_bars.py`) pulls
  NQ=F 1m/5m and ^VIX daily from Yahoo into `data/warehouse/market.duckdb` (gitignored, never
  committed). Upsert keyed by (symbol, interval, ts), so re-runs are safe and Yahoo revisions
  overwrite. Retries use exponential backoff. `bar_coverage` flags each expected trading day as
  ok / partial / missing / in_progress, plus `recoverable` (1m: 7 days, 5m: 55 days). A flagged
  day older than the window can never be refilled. The demo never depends on this store.
- **Scheduling**: run `make bars` at least every few days (daily is best) on the user's machine,
  e.g. cron `5 23 * * 1-5 cd ~/trading-analytics && make bars`. Claude does not install schedules.
- **Data quality policy (Phase 4)**: quarantine and report, never guess or impute. Exact duplicate
  rows are dropped; same id with different content raises `QualityError`; blank required fields,
  off-tick prices and prices >8% from the contract-day median are excluded; `is_active=false` is
  excluded from pairing. Anything excluded can desync position tracking, so it also raises an
  `excluded_fills_break_pairing` warning. Weekend/holiday trade dates, trade_date vs derived CME
  session date (rolls 18:00 ET; this rule is an assumption, check it on real data), display-time
  vs UTC->Israel, zero or varying commission, odd quantities, inconsistent orders are warnings.
  Reports show fill ids only, never accounts. `make quality` / `make quality-demo`;
  `make reconcile` prints the quality report first.
- **Clocks**: UTC is the only stored time; exchange (America/Chicago), ET and Israel are derived
  (`quality/timezone.py`). US and Israeli DST dates differ, so never hard-code offsets.
- **Warehouse + dbt (Phase 6)**: `make ingest [DATASET=demo|private]` cleans/pairs fills in Python
  and loads `raw.*` + `ingest.*` into `data/warehouse/<dataset>.duckdb` (gitignored);
  `make transform` runs `dbt build` (models + tests) there. Layers: raw (as exported) -> staging
  (stg_fills/trades/bars_1m/vix) -> intermediate (int_trade_context, ...) -> marts (Phase 7).
  Pairing stays in Python (stateful); analytics are SQL. `dbt_project/seeds/instruments.csv`
  must match `ingest/instruments.py` (a test enforces it).
- **MNQ trades use NQ=F bars as a proxy** (same Nasdaq-100 index; only the multiplier differs).
- **Context has no look-ahead**: volatility is the std of the previous 30 one-minute changes
  (excluding the entry bar); VIX is the previous day's close; distance from open uses the entry
  minute's open bar vs the 09:30 ET bar. MAE/MFE are outcomes and are limited by 1-minute bars:
  entry-minute bar excluded, exit-minute bar included, labelled `fills_only` when no bars lie
  between entry and exit.
- **Fill-vs-bar check**: assumes no basis between NQ=F and the traded contract unless <90% of a
  contract-day's fills fall inside their bars, then removes the median (fill - bar midpoint)
  basis; flags fills > `fill_bar_tol_pts` (5) outside the bar. A blind basis estimate adds its own
  noise and created false flags in the demo, hence the "assume zero" rule. Warn-only in dbt.
