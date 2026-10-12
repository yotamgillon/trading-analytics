-- Regimes must come from the stored thresholds (distribution over all bars), never from splitting
-- the trades into thirds. A forced tercile split makes a small sample come out exactly 3/3/3 and
-- disagrees with the threshold rule on any sample that is not itself evenly spread.
-- Returns rows (= fails) when
--   (a) any trade's regime differs from the rule applied to the stored thresholds, or
--   (b) the thresholds are not ordered, or
--   (c) a small sample (6-60 classified trades) is split into exactly equal counts.
with rule as (
    select
        c.trade_id, c.vol_regime as actual,
        case when c.vol_30m_pts is null or th.p33 is null then null
             when c.vol_30m_pts <= th.p33 then 'low'
             when c.vol_30m_pts <= th.p67 then 'mid'
             else 'high' end as expected,
        th.p33, th.p67
    from {{ ref('int_trade_context') }} as c
    left join {{ ref('int_vol_regime_thresholds') }} as th on th.bar_symbol = c.bar_symbol
),
counts as (
    select count(*) as n,
           count(*) filter (where actual = 'low') as n_low,
           count(*) filter (where actual = 'mid') as n_mid,
           count(*) filter (where actual = 'high') as n_high
    from rule where actual is not null
)
select trade_id, 'regime differs from stored-threshold rule' as problem
from rule where actual is distinct from expected
union all
select null, 'thresholds not ordered' from (select distinct p33, p67 from rule where p33 >= p67)
union all
select null, 'small sample forced into equal thirds'
from counts
where n between 6 and 60 and n_low = n_mid and n_mid = n_high
