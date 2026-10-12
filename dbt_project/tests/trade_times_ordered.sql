select * from {{ ref('stg_trades') }} where exit_time < entry_time
