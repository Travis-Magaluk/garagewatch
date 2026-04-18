-- Average temperature and humidity by hour-of-day × calendar month.
-- Produces 12 × 24 = 288 rows (one per month-hour combination).
-- Used for: heatmap panel showing daily cycles across seasons.

select
    cast(extract(month from read_at_local) as int)   as month_num,
    date_format(read_at_local, '%b')                 as month_name,
    cast(extract(hour from read_at_local) as int)    as hour_of_day,
    count(*)                                         as reading_count,
    cast(avg(temperature_f) as decimal(5,2))         as temp_f_avg,
    cast(avg(temperature_c) as decimal(5,2))         as temp_c_avg,
    cast(avg(humidity_percent) as decimal(5,2))      as humidity_avg
from {{ ref('stg_readings') }}
group by 1, 2, 3
order by 1, 3
