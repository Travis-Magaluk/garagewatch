-- One row per calendar day (local time).
-- Aggregates min, max, and average temperature and humidity.
-- Used for: daily band chart, calendar heatmap, extreme-days ranking.

select
    read_at_local::date                     as day,
    count(*)                                as reading_count,
    min(temperature_f)                      as temp_f_min,
    max(temperature_f)                      as temp_f_max,
    avg(temperature_f)::numeric(5,2)        as temp_f_avg,
    min(temperature_c)                      as temp_c_min,
    max(temperature_c)                      as temp_c_max,
    avg(temperature_c)::numeric(5,2)        as temp_c_avg,
    min(humidity_percent)                   as humidity_min,
    max(humidity_percent)                   as humidity_max,
    avg(humidity_percent)::numeric(5,2)     as humidity_avg
from {{ ref('stg_readings') }}
group by 1
order by 1
