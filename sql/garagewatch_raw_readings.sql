-- Catalog DDL for the silver Parquet table: garagewatch_raw.readings
--
-- This is the source table dbt reads from (see dbt/models/sources.yml). It is NOT
-- managed by dbt — dbt only treats it as a source — so its definition must live
-- here in the repo. Run this in the Athena query editor (or via the API) when
-- recreating the catalog from scratch.
--
-- Partition projection is the important part. Without it, every new month needs a
-- manual `MSCK REPAIR TABLE` / `ALTER TABLE ADD PARTITION`; if that registration
-- ever stops, Athena silently reads only the partitions it already knows about and
-- the dbt marts freeze at the last registered month with no error. Projection makes
-- Athena infer year=/month= partitions straight from the S3 path, so new months
-- (and back-filled gaps) light up automatically the moment the Parquet lands.
--
-- The transform that writes the underlying files is scripts/transform_to_silver.py.

CREATE EXTERNAL TABLE IF NOT EXISTS garagewatch_raw.readings (
  `timestamp`       timestamp,
  temperature_c     double,
  temperature_f     double,
  humidity_percent  double
)
PARTITIONED BY (
  year  string,
  month string
)
STORED AS PARQUET
LOCATION 's3://garagewatch-data/silver/readings/'
TBLPROPERTIES (
  'parquet.compress'          = 'SNAPPY',
  'projection.enabled'        = 'true',
  'projection.year.type'      = 'integer',
  'projection.year.range'     = '2025,2035',
  'projection.month.type'     = 'integer',
  'projection.month.range'    = '1,12',
  'projection.month.digits'   = '2',
  'storage.location.template' = 's3://garagewatch-data/silver/readings/year=${year}/month=${month}'
);

-- To enable projection on an already-existing table without recreating it
-- (this is what was applied to fix the May/June gap), run instead:
--
-- ALTER TABLE garagewatch_raw.readings SET TBLPROPERTIES (
--   'projection.enabled'        = 'true',
--   'projection.year.type'      = 'integer',
--   'projection.year.range'     = '2025,2035',
--   'projection.month.type'     = 'integer',
--   'projection.month.range'    = '1,12',
--   'projection.month.digits'   = '2',
--   'storage.location.template' = 's3://garagewatch-data/silver/readings/year=${year}/month=${month}'
-- );
