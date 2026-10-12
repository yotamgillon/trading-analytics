-- Trailing realised volatility per bar, using ONLY earlier bars (no look-ahead):
-- the standard deviation of the previous N one-minute point changes. Changes that span a gap
-- longer than 5 minutes (overnight, weekend, halts) are excluded.
with diffs as (
    select
        symbol,
        ts,
        case
            when ts - lag(ts) over w <= interval 5 minute then close - lag(close) over w
        end as d
    from {{ ref('stg_bars_1m') }}
    window w as (partition by symbol order by ts)
)
select
    symbol,
    ts,
    stddev_samp(d) over (
        partition by symbol order by ts
        rows between {{ var('vol_lookback_bars') }} preceding and 1 preceding
    ) as vol_pts,
    count(d) over (
        partition by symbol order by ts
        rows between {{ var('vol_lookback_bars') }} preceding and 1 preceding
    ) as vol_n
from diffs
