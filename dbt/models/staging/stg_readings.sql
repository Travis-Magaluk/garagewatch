-- Cleaned and typed view of raw sensor readings.
-- Casts columns to explicit types, filters out obviously bad sensor values,
-- and exposes the timestamp in both UTC and US/Eastern local time.

select
    timestamp::timestamptz                                          as read_at_utc,
    timestamp::timestamptz at time zone 'America/New_York'         as read_at_local,
    temperature_c::numeric(5,2)                                    as temperature_c,
    temperature_f::numeric(5,2)                                    as temperature_f,
    humidity_percent::numeric(5,2)                                  as humidity_percent
from {{ source('garage', 'readings') }}
where
    temperature_c between -20 and 60
    and humidity_percent between 0 and 100
    and timestamp is not null
