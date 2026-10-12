-- One row per trade with every condition the dashboard slices by. All context uses only
-- information available BEFORE the entry (no look-ahead), except MAE/MFE which are outcomes.
with t as (select * from {{ ref('stg_trades') }}),
timed as (
    select
        t.*,
        cast(t.entry_time_et as date) as entry_date_et,
        extract(hour from t.entry_time_et) * 60 + extract(minute from t.entry_time_et)
            as entry_minute_of_day_et
    from t
),
rth_open as (
    select symbol as bar_symbol, session_date_et, open as rth_open
    from {{ ref('stg_bars_1m') }}
    where minute_of_day_et = 570  -- 09:30 ET
),
joined as (
    select
        d.*,
        tb.bucket as time_bucket,
        tb.session,
        tb.sort_order as time_bucket_order,
        o.rth_open,
        eb.open as entry_bar_open,
        v.vol_pts,
        x.vix_close as vix_prev_close,
        e.mae_pts, e.mfe_pts, e.mae_usd, e.mfe_usd, e.bars_used, e.mae_mfe_basis,
        e.fills_outside_bar, e.fills_no_bar
    from timed as d
    left join {{ ref('time_buckets') }} as tb
        on d.entry_minute_of_day_et >= tb.start_minute and d.entry_minute_of_day_et < tb.end_minute
    left join rth_open as o
        on o.bar_symbol = d.bar_symbol and o.session_date_et = d.entry_date_et
    left join {{ ref('stg_bars_1m') }} as eb
        on eb.symbol = d.bar_symbol and eb.ts = date_trunc('minute', d.entry_time)
    left join {{ ref('int_bars_1m_vol') }} as v
        on v.symbol = d.bar_symbol and v.ts = date_trunc('minute', d.entry_time) and v.vol_n >= 15
    asof left join {{ ref('stg_vix') }} as x
        on d.entry_date_et > x.vix_date
    left join {{ ref('int_trade_extremes') }} as e using (trade_id)
)
select
    trade_id, account, symbol, contract, side, qty, max_position, n_fills,
    entry_time, exit_time, trade_date, entry_price, exit_price,
    gross_pnl, fees, commissions, net_pnl,
    entry_time_et, entry_time_israel,
    entry_date_et,
    isodow(entry_time_et) as weekday_num,
    dayname(entry_time_et) as weekday,
    cast(extract(hour from entry_time_et) as integer) as hour_et,
    time_bucket, session, time_bucket_order,
    duration_min,
    case when duration_min < 1 then '< 1 min'
         when duration_min < 3 then '1-3 min'
         when duration_min < 10 then '3-10 min'
         when duration_min < 30 then '10-30 min'
         else '30+ min' end as duration_bucket,
    rth_open,
    entry_bar_open,
    case when entry_minute_of_day_et >= 570 then entry_bar_open - rth_open end as dist_from_open_pts,
    case when entry_minute_of_day_et >= 570 then (entry_bar_open - rth_open) / rth_open end
        as dist_from_open_pct,
    case when entry_minute_of_day_et >= 570 then
        (entry_bar_open - rth_open) * (case when side = 'Long' then 1 else -1 end) end
        as dist_from_open_signed_pts,  -- >0: trading in the direction the day has moved
    vol_pts as vol_30m_pts,
    case when vol_pts is null then null
         else case ntile(3) over (order by vol_pts)
                when 1 then 'low' when 2 then 'mid' else 'high' end end as vol_regime,
    vix_prev_close,
    case when vix_prev_close is null then null
         when vix_prev_close < 15 then '< 15'
         when vix_prev_close < 20 then '15-20'
         when vix_prev_close < 25 then '20-25'
         else '25+' end as vix_regime,
    mae_pts, mfe_pts, mae_usd, mfe_usd, bars_used,
    coalesce(mae_mfe_basis, 'fills_only') as mae_mfe_basis,
    coalesce(fills_outside_bar, 0) as fills_outside_bar,
    coalesce(fills_no_bar, 0) as fills_no_bar,
    entry_bar_open is not null as has_entry_bar
from joined
