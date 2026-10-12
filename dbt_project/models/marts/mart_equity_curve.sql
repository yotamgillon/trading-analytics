-- GRAIN: account x symbol_scope ('ALL' or one symbol) x trade, ordered by (exit_time, trade_id).
-- equity      = start_balance + cumulative NET P&L, marked when each trade exits (realised only).
-- peak        = max(start_balance, highest equity so far): the starting point counts, so a losing
--               start is a drawdown from the start. drawdown_usd = peak - equity (>= 0).
-- drawdown_pct = drawdown_usd / peak, ONLY when start_balance > 0 (a percent of the account).
--               With start_balance 0 the peak is just peak profit, so a percent would be
--               meaningless (90% of a $50 peak); it stays null instead of being guessed.
-- The curve has no explicit "trade 0" row; a chart should prepend (start_balance) itself.
with scoped as ({{ scoped_trades(ref('fct_trades_enriched')) }}),
cum as (
    select
        account, symbol_scope, trade_id, symbol, side, exit_time, trade_date, outcome,
        gross_pnl, net_pnl,
        row_number() over w as trade_seq,
        sum(gross_pnl) over w as cum_gross_pnl,
        sum(net_pnl) over w as cum_net_pnl
    from scoped
    window w as (
        partition by account, symbol_scope order by exit_time, trade_id
        rows between unbounded preceding and current row
    )
),
eq as (
    select *, {{ var('start_balance') }} + cum_net_pnl as equity from cum
),
pk as (
    select
        *,
        greatest({{ var('start_balance') }}, max(equity) over (
            partition by account, symbol_scope order by exit_time, trade_id
            rows between unbounded preceding and current row)) as peak_equity
    from eq
)
select
    account, symbol_scope, trade_seq, trade_id, symbol, side, exit_time, trade_date, outcome,
    gross_pnl, net_pnl, cum_gross_pnl, cum_net_pnl, equity, peak_equity,
    peak_equity - equity as drawdown_usd,
    case when {{ var('start_balance') }} > 0 and peak_equity > 0
         then (peak_equity - equity) / peak_equity end as drawdown_pct,
    equity >= peak_equity as is_equity_high
from pk
