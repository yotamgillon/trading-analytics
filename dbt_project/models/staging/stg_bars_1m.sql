-- Valid 1-minute bars with ET clocks. Bars are for the continuous NQ future (NQ=F).
select
    symbol,
    ts,
    open,
    high,
    low,
    close,
    volume,
    timezone('America/New_York', ts)                                   as ts_et,
    cast(timezone('America/New_York', ts) as date)                     as session_date_et,
    extract(hour from timezone('America/New_York', ts)) * 60
        + extract(minute from timezone('America/New_York', ts))        as minute_of_day_et
from {{ source('raw', 'bars_1m') }}
where open > 0 and high >= low and close > 0
