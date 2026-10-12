-- Volatility-regime cut points, taken from the distribution of the SAME 30-minute volatility
-- measure over ALL regular-hours bars in the store, not from the trades. Splitting the trades
-- into terciles would force a 3/3/3 split on any sample (9 trades -> 3 low, 3 mid, 3 high) and
-- say nothing about whether the market was calm or wild when you traded.
-- Window and filter are identical to the trade-level measure: previous 30 one-minute changes
-- (>= 15 valid), bars starting 09:30-15:59 ET. Recomputed on every `dbt build`, so the cut points
-- sharpen as the bar store accumulates; n_bars / first / last date show how much they rest on.
select
    v.symbol as bar_symbol,
    quantile_cont(v.vol_pts, 1.0 / 3) as p33,
    quantile_cont(v.vol_pts, 2.0 / 3) as p67,
    count(*) as n_bars,
    min(b.session_date_et) as first_bar_date,
    max(b.session_date_et) as last_bar_date
from {{ ref('int_bars_1m_vol') }} as v
join {{ ref('stg_bars_1m') }} as b on b.symbol = v.symbol and b.ts = v.ts
where v.vol_n >= 15
  and b.minute_of_day_et >= 570 and b.minute_of_day_et < 960
group by 1
