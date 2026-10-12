-- GRAIN: account x symbol_scope ('ALL' or one symbol). Whole period; for a date filter use
-- mart_daily_performance (additive) so the numbers re-aggregate exactly.
with scoped as ({{ scoped_trades(ref('fct_trades_enriched')) }}),
agg as (
    select
        account, symbol_scope,
        {{ metric_aggregates() }},
        min(trade_date) as first_trade_date,
        max(trade_date) as last_trade_date,
        count(distinct trade_date) as trading_days,
        max(net_pnl) as best_trade_net,
        min(net_pnl) as worst_trade_net,
        stddev_samp(net_pnl) as net_pnl_stddev
    from scoped
    group by account, symbol_scope
),
dd as (
    select account, symbol_scope,
           max(drawdown_usd) as max_drawdown_usd,
           max(drawdown_pct) as max_drawdown_pct
    from {{ ref('mart_equity_curve') }}
    group by account, symbol_scope
),
st as (
    select account, symbol_scope,
           coalesce(max(streak_len) filter (where outcome = 'win'), 0) as max_win_streak,
           coalesce(max(streak_len) filter (where outcome = 'loss'), 0) as max_loss_streak
    from {{ ref('mart_streaks') }}
    group by account, symbol_scope
)
select
    agg.*,
    {{ metric_ratios() }},
    n_trades * 1.0 / trading_days as trades_per_day,
    coalesce(dd.max_drawdown_usd, 0) as max_drawdown_usd,
    dd.max_drawdown_pct,
    coalesce(st.max_win_streak, 0) as max_win_streak,
    coalesce(st.max_loss_streak, 0) as max_loss_streak
from agg
left join dd using (account, symbol_scope)
left join st using (account, symbol_scope)
