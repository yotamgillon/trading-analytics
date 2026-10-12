-- the buckets must cover every minute of the day exactly once
select * from (
    select sum(end_minute - start_minute) as covered, min(start_minute) as lo, max(end_minute) as hi
    from {{ ref('time_buckets') }}
) where covered != 1440 or lo != 0 or hi != 1440
