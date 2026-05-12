# Data quality

Quality is enforced at three layers in the pipeline. Each layer catches a different failure mode, and together they make it hard for bad data to silently reach the dashboards.

| Layer | Mechanism | What it catches |
|---|---|---|
| Ingestion | `stg_readings` `WHERE` clause | Physically impossible sensor values |
| Source | dbt source freshness | Pipeline halted; no new readings arriving |
| Marts | dbt schema + singular tests | Duplicates, nulls, sensor gaps |

## Layer 1 — staging filter

[`dbt/models/staging/stg_readings.sql`](../dbt/models/staging/stg_readings.sql) is the only thing between raw readings and the marts. It filters out physically impossible values:

```sql
where temperature_c between -20 and 60
  and humidity_percent between 0 and 100
  and timestamp is not null
```

SHT31D sensors occasionally return spurious values during I2C glitches — typically `-273.15 °C` (absolute zero) or `0`. Those readings are real rows in the bronze layer (the logger doesn't filter at ingest because the rule belongs in transform, not capture) but they never reach the marts because every mart `ref('stg_readings')`.

This is a deliberate architectural choice: keep the edge code dumb, and put the data rules in the warehouse where they can evolve under code review and version control.

## Layer 2 — source freshness

Declared in [`dbt/models/sources.yml`](../dbt/models/sources.yml):

```yaml
sources:
  - name: garage
    loaded_at_field: timestamp
    freshness:
      warn_after: {count: 2, period: hour}
      error_after: {count: 6, period: hour}
```

`dbt source freshness` runs `SELECT MAX(timestamp) FROM garage.readings` and checks the age of the most recent row. If it's older than 2 hours, dbt warns; older than 6 hours, dbt errors and the CI job fails.

This is the canary for the most insidious failure mode in a data pipeline: **stale data that looks fresh because old rows are still queryable**. Without a freshness check, a logger that died last Tuesday produces dashboards that look healthy until someone notices the timestamps.

## Layer 3 — schema and singular tests

### Schema tests

[`dbt/models/schema.yml`](../dbt/models/schema.yml) declares column-level tests:

- **`not_null`** on every column in `stg_readings` and on the grain columns (`day`, `month`) of `daily_summary` and `monthly_summary`.
- **`unique`** on `day` in `daily_summary` and `month` in `monthly_summary`.

The uniqueness tests are the canary for **duplicate readings making it through the silver merge**. `transform_to_silver.py` already does `drop_duplicates(subset=["timestamp"])`, but if that ever regressed — say, by reading from the wrong partition — `daily_summary` would aggregate the same readings twice, days would no longer be unique, and the dbt build would fail.

### Singular test — gap detection

[`dbt/tests/assert_no_recent_gaps.sql`](../dbt/tests/assert_no_recent_gaps.sql) catches the failure mode that freshness *misses*: the logger dies for 9 hours, recovers, and ships new readings before the freshness window closes. Freshness only knows the age of `MAX(timestamp)`. Continuity requires looking at the gaps between consecutive rows.

```sql
with recent as (
    select
        read_at_utc,
        lead(read_at_utc) over (order by read_at_utc) as next_read
    from {{ ref('stg_readings') }}
    where read_at_utc >= now() - interval '7' day
),

gaps as (
    select read_at_utc as gap_start,
           next_read   as gap_end,
           next_read - read_at_utc as gap_duration
    from recent
    where next_read - read_at_utc > interval '2' hour
)

select * from gaps
```

dbt singular tests pass when the query returns zero rows. Any gap longer than 2 hours in the last 7 days fails the test and (via CI) fails the workflow.

The 2-hour threshold is generous on purpose — the sensor reads every 60 seconds, so a 2-hour gap is unambiguous downtime, not a transient blip.

## Idempotency — the watermark pattern

Quality also lives in *how the data moves*, not just *what's in it*. Both export hops use watermarks so that re-running a stage is safe and never produces duplicates:

- **Postgres → Bronze** ([`scripts/export_to_s3.py`](../scripts/export_to_s3.py)): the watermark is the **last exported `timestamp`**, stored in `s3://garagewatch-data/watermark.json`. Queries are `WHERE timestamp > %s`, so a re-run of yesterday's export simply exports nothing new.
- **Bronze → Silver** ([`scripts/transform_to_silver.py`](../scripts/transform_to_silver.py)): the watermark is the **last processed S3 object key**, stored in `silver_watermark.json`. Listing only `key > last_key` ensures partial reruns pick up where they left off.

Idempotency isn't a data-quality *test*, but it's the property that makes the tests trustworthy — if a CI job retried after a transient AWS error, no test could distinguish that from a real data problem unless retries are guaranteed to produce the same result.

## What this doesn't catch yet

Honest list of gaps, for roadmap purposes:

- **Sensor calibration drift.** A reading of 72 °F is in-range whether it's accurate or not. Detecting drift would require a reference sensor or a known-stable indoor location for cross-checking.
- **Statistical anomalies on the gold layer.** Currently only the alerter's threshold check (humidity > 55%). A z-score or rolling-MAD test on `daily_summary` would catch slow drifts and unusual days that no threshold predicts.
- **Schema evolution.** If `readings` gained a new column, nothing currently fails — dbt would simply ignore the new column until `stg_readings` is updated. A column-presence test would close that loop.
- **Cost guardrails.** The cost overage described in [`docs/learnings/s3-cost-optimization.md`](learnings/s3-cost-optimization.md) was caught by AWS billing, not by anything in the pipeline. A CloudWatch alarm on Tier-1 request count would have caught it sooner.
