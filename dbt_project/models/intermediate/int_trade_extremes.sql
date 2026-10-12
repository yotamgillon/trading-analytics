-- MAE / MFE per trade from 1-minute bars, in points per contract.
--   MAE = worst adverse excursion from the average entry, MFE = best favourable excursion.
-- Honest limits of 1-minute data:
--   * the entry-minute bar is EXCLUDED (we cannot know whether its high/low came before entry);
--   * the exit-minute bar is INCLUDED (so MFE/MAE can be slightly overstated);
--   * bar prices are shifted by the contract basis so they are comparable with fill prices;
--   * all fill prices of the trade (scale in/out) are also considered, so a trade that opens and
--     closes inside one minute still gets a (fills-only) value, labelled 'fills_only'.
with t as (select * from {{ ref('stg_trades') }}),
bar_ext as (
    select t.trade_id, max(b.high) as max_high, min(b.low) as min_low, count(*) as bars_used
    from t
    join {{ ref('stg_bars_1m') }} as b
        on b.symbol = t.bar_symbol
       and b.ts > date_trunc('minute', t.entry_time)
       and b.ts <= date_trunc('minute', t.exit_time)
    group by 1
),
fill_ext as (
    select
        t.trade_id,
        max(f.price) as max_fill,
        min(f.price) as min_fill,
        avg(c.basis_pts) as basis_pts,
        count(*) filter (where c.status = 'outside_bar') as fills_outside_bar,
        count(*) filter (where c.status = 'no_bar') as fills_no_bar
    from t
    join {{ ref('stg_fills') }} as f
        on f.account = t.account and f.contract = t.contract and f.is_active
       and f.fill_time between t.entry_time and t.exit_time
    left join {{ ref('int_fill_bar_check') }} as c using (fill_id)
    group by 1
),
bounds as (
    select
        t.trade_id, t.side, t.entry_price, t.multiplier, t.qty,
        coalesce(b.bars_used, 0) as bars_used,
        greatest(t.entry_price, t.exit_price, coalesce(f.max_fill, t.entry_price),
                 coalesce(b.max_high + coalesce(f.basis_pts, 0), t.entry_price)) as hi,
        least(t.entry_price, t.exit_price, coalesce(f.min_fill, t.entry_price),
              coalesce(b.min_low + coalesce(f.basis_pts, 0), t.entry_price)) as lo,
        coalesce(f.fills_outside_bar, 0) as fills_outside_bar,
        coalesce(f.fills_no_bar, 0) as fills_no_bar
    from t
    left join bar_ext as b using (trade_id)
    left join fill_ext as f using (trade_id)
)
select
    trade_id,
    case when side = 'Long' then entry_price - lo else hi - entry_price end as mae_pts,
    case when side = 'Long' then hi - entry_price else entry_price - lo end as mfe_pts,
    (case when side = 'Long' then entry_price - lo else hi - entry_price end)
        * multiplier * qty as mae_usd,
    (case when side = 'Long' then hi - entry_price else entry_price - lo end)
        * multiplier * qty as mfe_usd,
    bars_used,
    case when bars_used > 0 then 'bars' else 'fills_only' end as mae_mfe_basis,
    fills_outside_bar,
    fills_no_bar
from bounds
