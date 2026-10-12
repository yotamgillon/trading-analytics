-- GRAIN: account x weekday x ET entry hour (the heatmap). Sample sizes are small per cell:
-- always read n_trades with the metric; `low_sample` flags cells under 30 trades.
with agg as (
    select account, weekday_num, weekday, hour_et, {{ metric_aggregates() }}
    from {{ ref('fct_trades_enriched') }}
    group by account, weekday_num, weekday, hour_et
)
select agg.*, {{ metric_ratios() }}, n_trades < 30 as low_sample
from agg
