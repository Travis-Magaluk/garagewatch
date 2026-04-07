-- One row per calendar month.
-- Includes percentiles for box-plot style visualization.
-- Used for: monthly distribution panel.

select
    date_trunc('month', read_at_local)::date        as month,
    to_char(read_at_local, 'YYYY-MM')               as month_label,
    count(*)                                         as reading_count,

    -- Temperature (F)
    min(temperature_f)                               as temp_f_min,
    percentile_cont(0.25) within group
        (order by temperature_f)::numeric(5,2)       as temp_f_p25,
    percentile_cont(0.50) within group
        (order by temperature_f)::numeric(5,2)       as temp_f_median,
    percentile_cont(0.75) within group
        (order by temperature_f)::numeric(5,2)       as temp_f_p75,
    max(temperature_f)                               as temp_f_max,
    avg(temperature_f)::numeric(5,2)                 as temp_f_avg,

    -- Humidity
    min(humidity_percent)                            as humidity_min,
    percentile_cont(0.25) within group
        (order by humidity_percent)::numeric(5,2)    as humidity_p25,
    percentile_cont(0.50) within group
        (order by humidity_percent)::numeric(5,2)    as humidity_median,
    percentile_cont(0.75) within group
        (order by humidity_percent)::numeric(5,2)    as humidity_p75,
    max(humidity_percent)                            as humidity_max,
    avg(humidity_percent)::numeric(5,2)              as humidity_avg

from {{ ref('stg_readings') }}
group by 1, 2
order by 1
