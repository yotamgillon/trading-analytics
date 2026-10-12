-- Every mart must tell the same story as the fact table. Returns one row per broken rule.
with f as (
    select account, count(*) as n, sum(net_pnl) as net, sum(gross_pnl) as gross
    from {{ ref('fct_trades_enriched') }} group by account
),
k as (select account, n_trades, net_pnl, gross_pnl from {{ ref('mart_kpis') }}
      where symbol_scope = 'ALL'),
d as (select account, sum(n_trades) as n, sum(net_pnl) as net
      from {{ ref('mart_daily_performance') }} group by account),
e as (select account, sum(net_pnl) filter (where trade_seq = mx) as final_net
      from (select *, max(trade_seq) over (partition by account, symbol_scope) as mx,
                   cum_net_pnl as net_pnl_unused
            from {{ ref('mart_equity_curve') }} where symbol_scope = 'ALL')
      group by account),
dim as (select account, dimension, sum(n_trades) as n, sum(net_pnl) as net
        from {{ ref('mart_perf_by_dimension') }} group by account, dimension),
hw as (select account, sum(n_trades) as n from {{ ref('mart_perf_hour_weekday') }}
       group by account)
select 'kpi trades/net/gross differ from fact' as problem, f.account
from f join k using (account)
where f.n != k.n_trades or abs(f.net - k.net_pnl) > 1e-6 or abs(f.gross - k.gross_pnl) > 1e-6
union all
select 'daily mart does not add up to fact', f.account
from f join d using (account) where f.n != d.n or abs(f.net - d.net) > 1e-6
union all
select 'a dimension does not partition the trades: ' || dim.dimension, f.account
from f join dim using (account) where f.n != dim.n or abs(f.net - dim.net) > 1e-6
union all
select 'hour x weekday does not partition the trades', f.account
from f join hw using (account) where f.n != hw.n
