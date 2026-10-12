-- GRAIN: one row per trade. The fact table every other mart is built from.
-- Win/loss is classified on `win_loss_basis` (gross by default); a trade at exactly 0 is a scratch.
{% set pnl = 'net_pnl' if var('win_loss_basis') == 'net' else 'gross_pnl' %}
select
    c.*,
    {{ pnl }} > 0 as is_win,
    {{ pnl }} < 0 as is_loss,
    case when {{ pnl }} > 0 then 'win' when {{ pnl }} < 0 then 'loss' else 'scratch' end as outcome
from {{ ref('int_trade_context') }} as c
