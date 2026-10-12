-- One row per cleaned fill, with exchange/ET/Israel clocks derived from the single UTC source.
select
    f.fill_id,
    f.order_id,
    f.account,
    f.symbol,
    f.contract,
    f.side,
    f.qty,
    f.price,
    f.fill_time,
    f.trade_date,
    f.commission,
    f.fees,
    f.multiplier,
    f.is_active,
    i.bar_symbol,
    date_trunc('minute', f.fill_time)                       as fill_minute,
    timezone('America/New_York', f.fill_time)               as fill_time_et,
    cast(timezone('America/New_York', f.fill_time) as date) as fill_date_et,
    timezone('America/Chicago', f.fill_time)                as fill_time_exchange,
    timezone('Asia/Jerusalem', f.fill_time)                 as fill_time_israel
from {{ source('ingest', 'fills') }} as f
left join {{ ref('instruments') }} as i on i.symbol = f.symbol
