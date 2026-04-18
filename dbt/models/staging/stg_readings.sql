-- Cleaned and typed view of raw sensor readings.
-- Casts columns to explicit types, filters out obviously bad sensor values,
-- and exposes the timestamp in both UTC and US/Eastern local time.

select
    cast(timestamp as timestamp)                                                      as read_at_utc,
    cast(at_timezone(cast(timestamp as timestamp with time zone), 'America/New_York') as timestamp) as read_at_local,
    cast(temperature_c as decimal(5,2))                                               as temperature_c,
    cast(temperature_f as decimal(5,2))                                               as temperature_f,
    cast(humidity_percent as decimal(5,2))                                            as humidity_percent
from {{ source('garage', 'readings') }}
where
    temperature_c between -20 and 60
    and humidity_percent between 0 and 100
    and timestamp is not null
