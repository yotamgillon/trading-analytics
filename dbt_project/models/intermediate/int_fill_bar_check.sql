-- Does each fill's price sit inside its 1-minute bar?
-- The bars are the continuous future (NQ=F); fills are a specific contract (e.g. NQZ6), so they
-- can differ by the basis. We assume NO basis unless the data says otherwise: if at least 90% of
-- a contract-day's fills already sit inside their bars the basis is 0 (when NQ=F is the same
-- contract as the fills, as in the front month, it is). Otherwise the basis is the median of
-- (fill - bar midpoint) over that contract-day (contract-wide median when the day has fewer than
-- 3 fills). Then we measure how far each fill lies outside [low, high] after removing it.
-- Estimating a basis blindly would add noise of its own and create false flags.
-- MNQ fills are checked against NQ bars (same index, proxy).
with joined as (
    select
        f.fill_id, f.contract, f.fill_date_et, f.price,
        b.low as bar_low, b.high as bar_high,
        f.price - (b.high + b.low) / 2.0 as d,
        case when b.low is null then null
             when f.price between b.low and b.high then 1.0 else 0.0 end as inside
    from {{ ref('stg_fills') }} as f
    left join {{ ref('stg_bars_1m') }} as b
        on b.symbol = f.bar_symbol and b.ts = f.fill_minute
    where f.is_active
),
day_basis as (
    select contract, fill_date_et, count(d) as n_day,
           case when avg(inside) >= 0.9 then 0 else median(d) end as basis_day
    from joined group by 1, 2
),
contract_basis as (
    select contract,
           case when avg(inside) >= 0.9 then 0 else median(d) end as basis_contract
    from joined group by 1
),
with_basis as (
    select
        j.*,
        case when db.n_day >= 3 then db.basis_day
             else coalesce(cb.basis_contract, 0) end as basis_pts
    from joined as j
    left join day_basis as db using (contract, fill_date_et)
    left join contract_basis as cb using (contract)
),
measured as (
    select
        *,
        case when bar_low is null then null
             else greatest(bar_low - (price - basis_pts), (price - basis_pts) - bar_high, 0)
        end as residual_pts
    from with_basis
)
select
    fill_id, contract, fill_date_et, price, bar_low, bar_high, basis_pts, residual_pts,
    case when bar_low is null then 'no_bar'
         when residual_pts > {{ var('fill_bar_tol_pts') }} then 'outside_bar'
         else 'ok' end as status
from measured
