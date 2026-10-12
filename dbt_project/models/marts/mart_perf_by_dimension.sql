-- GRAIN: account x dimension x bucket. Each trade lands in exactly one bucket per dimension, so
-- n_trades summed over the buckets of one dimension equals the number of trades (tested).
-- is_actionable = knowable BEFORE entering. Duration is not: it is only known after the trade and
-- is mechanically tied to the outcome (a nearer stop is hit sooner), so it must not be sold as a
-- "when to trade" condition.
{% set dims = [
    ('hour', "cast(hour_et as varchar)", "hour_et", true),
    ('weekday', "weekday", "weekday_num", true),
    ('time_bucket', "time_bucket", "time_bucket_order", true),
    ('session', "session",
        "case session when 'Pre-market' then 1 when 'RTH' then 2 when 'Post-market' then 3 else 4 end",
        true),
    ('vol_regime', "coalesce(vol_regime, 'n/a')",
        "case vol_regime when 'low' then 1 when 'mid' then 2 when 'high' then 3 else 4 end", true),
    ('vix_regime', "coalesce(vix_regime, 'n/a')",
        "case vix_regime when '< 15' then 1 when '15-20' then 2 when '20-25' then 3 when '25+' then 4 else 5 end",
        true),
    ('duration', "duration_bucket",
        "case duration_bucket when '< 1 min' then 1 when '1-3 min' then 2 when '3-10 min' then 3 when '10-30 min' then 4 else 5 end",
        false),
    ('side', "side", "case side when 'Long' then 1 else 2 end", true),
    ('symbol', "symbol", "0", true),
    ('open_alignment',
        "case when dist_from_open_signed_pts is null then 'n/a' when dist_from_open_signed_pts > 0 then 'with the day move' when dist_from_open_signed_pts < 0 then 'against the day move' else 'at the open' end",
        "case when dist_from_open_signed_pts is null then 3 when dist_from_open_signed_pts > 0 then 1 else 2 end",
        true),
] %}
with long as (
    {% for name, bucket, order, actionable in dims %}
    select
        account, '{{ name }}' as dimension, {{ bucket }} as bucket, {{ order }} as bucket_order,
        {{ actionable }} as is_actionable,
        is_win, is_loss, gross_pnl, net_pnl, commissions, fees, duration_min
    from {{ ref('fct_trades_enriched') }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),
agg as (
    select account, dimension, bucket, bucket_order, is_actionable, {{ metric_aggregates() }}
    from long
    group by account, dimension, bucket, bucket_order, is_actionable
)
select
    agg.*,
    {{ metric_ratios() }},
    n_trades * 1.0 / sum(n_trades) over (partition by account, dimension) as share_of_trades,
    n_trades < 30 as low_sample
from agg
