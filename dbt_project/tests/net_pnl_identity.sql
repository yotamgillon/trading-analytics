-- net = gross - fees - commissions, always.
select * from {{ ref('stg_trades') }}
where abs(gross_pnl - fees - commissions - net_pnl) > 1e-6
