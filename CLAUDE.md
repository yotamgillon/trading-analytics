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
