-- Top and bottom ranked days for temperature and humidity over the past year.
-- Used for: "Coldest 15 days" and "Most humid 15 days" table panels in Grafana.

with last_year as (
    select *
    from {{ ref('daily_summary') }}
    where day >= current_date - interval '1' year
),

coldest as (
    select
        day,
        temp_f_avg,
        temp_f_min,
        humidity_avg,
        'coldest' as category,
        row_number() over (order by temp_f_avg asc) as rank
    from last_year
),

hottest as (
    select
        day,
        temp_f_avg,
        temp_f_max,
        humidity_avg,
        'hottest' as category,
        row_number() over (order by temp_f_avg desc) as rank
    from last_year
),

most_humid as (
    select
        day,
        humidity_avg,
        humidity_max,
        temp_f_avg,
        'most_humid' as category,
        row_number() over (order by humidity_avg desc) as rank
    from last_year
)

select day, temp_f_avg, temp_f_min as temp_f_extreme, humidity_avg, category, rank
from coldest where rank <= 15
union all
select day, temp_f_avg, temp_f_max as temp_f_extreme, humidity_avg, category, rank
from hottest where rank <= 15
union all
select day, temp_f_avg, null as temp_f_extreme, humidity_avg, category, rank
from most_humid where rank <= 15
order by category, rank
