-- Identifies consecutive windows where humidity stayed above 60%.
-- Uses the "gaps and islands" pattern: readings are grouped into islands
-- of consecutive high-humidity readings (30-min intervals, so a gap >1 reading breaks the streak).
-- Used for: "Longest high-humidity streaks" table panel.

with flagged as (
    select
        read_at_local,
        humidity_percent,
        case when humidity_percent >= 60 then 1 else 0 end as is_high
    from {{ ref('stg_readings') }}
),

-- Assign a group number that increments each time the flag changes
grouped as (
    select
        read_at_local,
        humidity_percent,
        is_high,
        row_number() over (order by read_at_local)
            - row_number() over (partition by is_high order by read_at_local) as grp
    from flagged
),

streaks as (
    select
        grp,
        is_high,
        min(read_at_local)              as streak_start,
        max(read_at_local)              as streak_end,
        count(*)                        as reading_count,
        -- 30 min per reading
        count(*) * 30                   as duration_minutes,
        cast(avg(humidity_percent) as decimal(5,2)) as avg_humidity,
        cast(max(humidity_percent) as decimal(5,2)) as peak_humidity
    from grouped
    where is_high = 1
    group by grp, is_high
)

select
    streak_start,
    streak_end,
    duration_minutes,
    round(duration_minutes / 60.0, 1)   as duration_hours,
    avg_humidity,
    peak_humidity,
    reading_count
from streaks
where duration_minutes >= 60  -- only streaks lasting at least 1 hour
order by duration_minutes desc
limit 50
