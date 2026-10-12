{# Fails when more than `threshold` of the rows have `column_name` = `value`. #}
{% test share_below(model, column_name, value, threshold) %}
select share
from (
    select avg(case when {{ column_name }} = '{{ value }}' then 1.0 else 0.0 end) as share
    from {{ model }}
)
where share > {{ threshold }}
{% endtest %}
