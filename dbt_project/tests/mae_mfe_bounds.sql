-- excursions are non-negative and, for a closed trade, MFE >= the realised move if favourable
select * from {{ ref('int_trade_extremes') }}
where mae_pts < 0 or mfe_pts < 0
