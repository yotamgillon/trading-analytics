-- GRAIN: account x symbol x trade_date (the platform's session date of the exit fill).
-- Additive components only: sum them over any filter (dates, symbols) and the ratios computed
-- from the sums equal the ratios computed on the underlying trades. Matches the platform's
-- per-day, per-symbol rows, which is what `make reconcile` compares against.
select
    account, symbol, trade_date,
    {{ metric_aggregates() }}
from {{ ref('fct_trades_enriched') }}
group by account, symbol, trade_date
