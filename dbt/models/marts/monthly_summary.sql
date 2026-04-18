-- One row per calendar month.
-- Includes percentiles for box-plot style visualization.
-- Used for: monthly distribution panel.

select
    cast(date_trunc('month', read_at_local) as date)   as month,
    date_format(read_at_local, '%Y-%m')                as month_label,
    count(*)                                           as reading_count,

    -- Temperature (F)
    min(temperature_f)                                             as temp_f_min,
    cast(approx_percentile(temperature_f, 0.25) as decimal(5,2))  as temp_f_p25,
    cast(approx_percentile(temperature_f, 0.50) as decimal(5,2))  as temp_f_median,
    cast(approx_percentile(temperature_f, 0.75) as decimal(5,2))  as temp_f_p75,
    max(temperature_f)                                             as temp_f_max,
    cast(avg(temperature_f) as decimal(5,2))                       as temp_f_avg,

    -- Humidity
    min(humidity_percent)                                             as humidity_min,
    cast(approx_percentile(humidity_percent, 0.25) as decimal(5,2))  as humidity_p25,
    cast(approx_percentile(humidity_percent, 0.50) as decimal(5,2))  as humidity_median,
    cast(approx_percentile(humidity_percent, 0.75) as decimal(5,2))  as humidity_p75,
    max(humidity_percent)                                             as humidity_max,
    cast(avg(humidity_percent) as decimal(5,2))                       as humidity_avg

from {{ ref('stg_readings') }}
group by 1, 2
order by 1
