-- GRAIN: account x symbol_scope x streak (a maximal run of consecutive wins or of consecutive
-- losses, in exit order). A scratch trade ends any streak and belongs to none.
-- Gaps-and-islands: rn - rank within outcome is constant inside an unbroken run.
with scoped as ({{ scoped_trades(ref('fct_trades_enriched')) }}),
ordered as (
    select
        account, symbol_scope, trade_id, outcome, exit_time, gross_pnl, net_pnl,
        row_number() over (partition by account, symbol_scope order by exit_time, trade_id) as rn
    from scoped
),
islands as (
    select
        *,
        rn - row_number() over (
            partition by account, symbol_scope, outcome order by exit_time, trade_id
        ) as grp
    from ordered
    where outcome in ('win', 'loss')
)
select
    account, symbol_scope, outcome,
    row_number() over (partition by account, symbol_scope order by min(rn)) as streak_id,
    count(*) as streak_len,
    min(exit_time) as started_at,
    max(exit_time) as ended_at,
    sum(gross_pnl) as gross_pnl,
    sum(net_pnl) as net_pnl
from islands
group by account, symbol_scope, outcome, grp
