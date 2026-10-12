-- the enrichment joins must neither drop nor duplicate trades
select * from (
    select
        (select count(*) from {{ ref('stg_trades') }}) as n_trades,
        (select count(*) from {{ ref('int_trade_context') }}) as n_context
) where n_trades != n_context
