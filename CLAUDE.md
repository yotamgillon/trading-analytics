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
  (non-look-ahead) scaling. Expected gross P&L is zero and commissions make expected net slightly negative; the REALIZED
  P&L of any one sample (the demo's included, which happens to be positive) is just noise. Verified by permutation
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
- **Vol regime = threshold rule, not terciles of the trades.** `int_vol_regime_thresholds` stores
  p33/p67 of the same 30-minute volatility over ALL regular-hours bars in the store (same window,
  same >=15-valid-changes and 09:30-16:00 ET filter), and `int_trade_context` applies them
  (`<= p33` low, `<= p67` mid, else high). An `ntile` over the trades forced a small sample into
  exact thirds (9 trades -> 3/3/3) and said nothing about the market. Singular test
  `vol_regime_not_forced_to_thirds` fails on rule mismatch, unordered thresholds, or a 6-60 trade
  sample split into equal counts; pytest also proves the test catches the old tercile behaviour.
  Caveat: thresholds are recomputed on each `dbt build`, so they are only as good as the bar store
  (`n_bars`, `first_bar_date`, `last_bar_date` are stored beside them) and shift as bars accumulate.
  Trades cluster at the volatile open, so regime shares are NOT expected to be thirds.
- **Marts (Phase 7)**, all metrics in SQL, defined once in `dbt_project/macros/metrics.sql`:
  `fct_trades_enriched` (trade), `mart_equity_curve` (account x symbol_scope x trade),
  `mart_streaks` (run of wins/losses), `mart_kpis` (account x symbol_scope), `mart_perf_by_dimension`
  (account x dimension x bucket; `is_actionable` false for duration), `mart_perf_hour_weekday`
  (heatmap), `mart_daily_performance` (account x symbol x trade_date, ADDITIVE: sum the components
  over any date/symbol filter and the ratios are exact). symbol_scope is 'ALL' or one symbol.
- **Metric definitions**: win/loss by `win_loss_basis` (gross default; scratch = exactly 0 and is
  neither); win_rate = wins / all trades; avg_win/avg_loss GROSS (avg_loss negative); payoff =
  avg_win / |avg_loss|; expectancy_net = mean net P&L per trade (expectancy_gross also given);
  profit_factor = gross profit / |gross loss| (profit_factor_net classifies by net); costs % of gross
  profit always, % of gross P&L only when gross P&L > 0; streaks: a scratch ends a streak.
- **Equity and drawdown**: equity = `start_balance` (dbt var, default 0) + cumulative NET P&L,
  realised at each trade's exit, ordered by (exit_time, trade_id). Default start is ZERO because the
  prop-firm balance is not in the export, so the curve is relative to the first trade. Peak =
  max(start_balance, highest equity so far), so the starting point counts and a losing start is a
  drawdown. Max drawdown is the largest peak-to-trough drop in dollars (balance independent);
  drawdown % is produced only when `start_balance > 0` and is NULL otherwise (never guessed).
  Use `dbt build --vars '{start_balance: 50000}'`. No explicit "trade 0" row; charts prepend it.
- **Mart tests**: dbt grain-uniqueness + consistency singular tests; pytest compares every KPI,
  dimension, heatmap cell, daily row and the equity/drawdown path against pandas/numpy, plus a
  hand-computed 9-trade fixture (exact numbers incl. streaks split by a scratch, drawdown 203.5).
