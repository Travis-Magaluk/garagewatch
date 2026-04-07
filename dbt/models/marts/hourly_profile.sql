-- Average temperature and humidity by hour-of-day × calendar month.
-- Produces 12 × 24 = 288 rows (one per month-hour combination).
-- Used for: heatmap panel showing daily cycles across seasons.

select
    extract(month from read_at_local)::int      as month_num,
    to_char(read_at_local, 'Mon')               as month_name,
    extract(hour from read_at_local)::int       as hour_of_day,
    count(*)                                    as reading_count,
    avg(temperature_f)::numeric(5,2)            as temp_f_avg,
    avg(temperature_c)::numeric(5,2)            as temp_c_avg,
    avg(humidity_percent)::numeric(5,2)         as humidity_avg
from {{ ref('stg_readings') }}
group by 1, 2, 3
order by 1, 3
