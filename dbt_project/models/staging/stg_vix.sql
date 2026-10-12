select cast(date as date) as vix_date, close as vix_close
from {{ source('raw', 'vix_daily') }}
where close > 0
