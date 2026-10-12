Sample data quality report (demo data with deliberately injected defects)

## Data quality report

1184 raw rows -> 1179 clean fills

- **FIXED** `duplicate_rows` x2: exact duplicate rows dropped (overlapping exports) (fill ids 800000000346, 800000002080)
- **FIXED** `missing_values` x1: rows with a blank required field were excluded (never imputed) (fill ids 800000000239)
- **FIXED** `off_tick_price` x1: price is not a multiple of the tick size, so it cannot be an exchange fill; excluded (fill ids 800000001480)
- **FIXED** `price_outlier` x1: price more than 8% from the contract-day median (fat-finger or typo); excluded (fill ids 800000001773)
- **FIXED** `inactive_fills` x1: is_active=false fills excluded from pairing (meaning of the flag is unconfirmed) (fill ids 999999999001)
- **WARN** `display_time_mismatch` x1: platform display time differs from UTC converted to Israel time (kept; UTC is the source of truth) (fill ids 800000001368)
- **WARN** `excluded_fills_break_pairing` x3: fills were excluded on contract(s) MNQH6, MNQM6, NQM6; position tracking is out of step from the first exclusion, so trades on these contracts after that point are unreliable until the export is corrected
- **WARN** `large_quantity` x1: fill quantity above 100 contracts (kept) (fill ids 800000000302)
- **WARN** `zero_commission` x1: fills with zero commission (kept; fees % will be understated) (fill ids 800000000774)
- **WARN** `commission_rate_varies` x2: MNQ commission per contract takes several values [0.003, 0.5] (kept)
- **WARN** `unmatched_open_position` x3: position still open at the end of the data; no exit invented, no trade created: MNQH6 Long 498 @ 31841.56; MNQM6 Short 2 @ 27417.75; NQM6 Long 3 @ 27317.08
- **INFO** `summary` x413: 1178 active fills paired into 413 flat-to-flat trades
