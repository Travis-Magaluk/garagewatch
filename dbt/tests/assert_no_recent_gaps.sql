-- Fails if there is any gap longer than 2 hours in the last 7 days.
-- A "gap" is defined as two consecutive readings more than 2 hours apart.
-- This test catches sensor downtime or logging failures.

with recent as (
    select
        read_at_utc,
        lead(read_at_utc) over (order by read_at_utc) as next_read
    from {{ ref('stg_readings') }}
    where read_at_utc >= now() - interval '7' day
),

gaps as (
    select
        read_at_utc as gap_start,
        next_read   as gap_end,
        next_read - read_at_utc as gap_duration
    from recent
    where next_read - read_at_utc > interval '2' hour
)

-- dbt singular tests pass when 0 rows are returned
select * from gaps
