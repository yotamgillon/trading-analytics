{# Fails if the model has more than one row for a combination of the grain columns. #}
{% test unique_grain(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
