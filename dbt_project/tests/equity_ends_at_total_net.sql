-- the last point of every equity curve equals that scope's total net P&L (+ start balance)
select c.account, c.symbol_scope, 'equity curve ends away from total net P&L' as problem
from {{ ref('mart_equity_curve') }} as c
join (
    select account, symbol_scope, max(trade_seq) as last_seq
    from {{ ref('mart_equity_curve') }} group by 1, 2
) as l on l.account = c.account and l.symbol_scope = c.symbol_scope and l.last_seq = c.trade_seq
join {{ ref('mart_kpis') }} as k on k.account = c.account and k.symbol_scope = c.symbol_scope
where abs(c.equity - ({{ var('start_balance') }} + k.net_pnl)) > 1e-6
