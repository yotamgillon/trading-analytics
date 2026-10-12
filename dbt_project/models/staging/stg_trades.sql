-- One row per flat-to-flat trade (per account and contract), pairing done upstream in Python.
select
    t.trade_id,
    t.account,
    t.symbol,
    t.contract,
    t.side,
    t.qty,
    t.entry_time,
    t.exit_time,
    t.trade_date,
    t.entry_price,
    t.exit_price,
    t.gross_pnl,
    t.fees,
    t.commissions,
    t.net_pnl,
    t.n_fills,
    t.max_position,
    i.multiplier,
    i.bar_symbol,
    timezone('America/New_York', t.entry_time) as entry_time_et,
    timezone('America/New_York', t.exit_time)  as exit_time_et,
    timezone('Asia/Jerusalem', t.entry_time)   as entry_time_israel,
    epoch(t.exit_time - t.entry_time) / 60.0   as duration_min
from {{ source('ingest', 'trades') }} as t
left join {{ ref('instruments') }} as i on i.symbol = t.symbol
