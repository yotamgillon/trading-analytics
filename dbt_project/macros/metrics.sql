{# Metric definitions live here ONCE and are reused by every mart, so a KPI can never disagree
   with the same KPI sliced another way. Two steps: additive aggregates, then ratios of them.
   Needs columns: is_win, is_loss, gross_pnl, net_pnl, commissions, fees, duration_min. #}

{% macro metric_aggregates() %}
    count(*) as n_trades,
    count(*) filter (where is_win) as n_wins,
    count(*) filter (where is_loss) as n_losses,
    count(*) filter (where not is_win and not is_loss) as n_scratch,
    coalesce(sum(gross_pnl) filter (where is_win), 0) as gross_profit,
    coalesce(sum(gross_pnl) filter (where is_loss), 0) as gross_loss,
    sum(gross_pnl) as gross_pnl,
    sum(commissions) as commissions,
    sum(fees) as fees,
    sum(net_pnl) as net_pnl,
    coalesce(sum(net_pnl) filter (where net_pnl > 0), 0) as net_profit,
    coalesce(sum(net_pnl) filter (where net_pnl < 0), 0) as net_loss,
    sum(duration_min) as sum_duration_min
{% endmacro %}

{# Ratios of the aggregates above. avg_win / avg_loss are GROSS (as the platform shows them);
   avg_loss is negative. profit_factor is gross; profit_factor_net classifies by net P&L. #}
{% macro metric_ratios() %}
    n_wins * 1.0 / n_trades as win_rate,
    gross_profit / nullif(n_wins, 0) as avg_win,
    gross_loss / nullif(n_losses, 0) as avg_loss,
    (gross_profit / nullif(n_wins, 0)) / abs(gross_loss / nullif(n_losses, 0)) as payoff_ratio,
    gross_pnl / n_trades as expectancy_gross,
    net_pnl / n_trades as expectancy_net,
    gross_profit / nullif(abs(gross_loss), 0) as profit_factor,
    net_profit / nullif(abs(net_loss), 0) as profit_factor_net,
    commissions + fees as costs,
    (commissions + fees) / nullif(gross_profit, 0) as costs_pct_of_gross_profit,
    case when gross_pnl > 0 then (commissions + fees) / gross_pnl end as costs_pct_of_gross_pnl,
    sum_duration_min / n_trades as avg_duration_min
{% endmacro %}

{# Every trade twice over: once under scope 'ALL' and once under its own symbol, so equity,
   streaks and KPIs exist per symbol and overall with the same SQL. #}
{% macro scoped_trades(relation) %}
    select 'ALL' as symbol_scope, * from {{ relation }}
    union all
    select symbol as symbol_scope, * from {{ relation }}
{% endmacro %}
