#!/usr/bin/env python3
"""
Transform bronze CSV.gz files from S3 to Parquet silver layer.

Watermark pattern:
  1. Read last processed bronze S3 key from silver_watermark.json
  2. List bronze files with key > watermark
  3. For each affected (year, month) partition, re-read all bronze files
     for that partition, merge, and write a single Parquet file to silver/
  4. Update watermark to last processed bronze key
"""

import gzip
import io
import json
import logging

import boto3
import pandas as pd
from botocore.exceptions import ClientError

BUCKET = "garagewatch-data"
BRONZE_PREFIX = "raw/readings/"
SILVER_PREFIX = "silver/readings/"
SILVER_WATERMARK_KEY = "silver_watermark.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_silver_watermark(s3):
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=SILVER_WATERMARK_KEY)
        return json.loads(obj["Body"].read())["last_key"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            logger.info("No silver watermark — processing all bronze files")
            return ""
        raise


def list_new_bronze_files(s3, after_key):
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=BRONZE_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".csv.gz") and key > after_key:
                keys.append(key)
    return sorted(keys)


def partition_from_key(key):
    # key: raw/readings/year=2025/month=01/readings_20250101_120000.csv.gz
    parts = key.split("/")
    return parts[2].split("=")[1], parts[3].split("=")[1]  # year, month


def list_all_bronze_for_partition(s3, year, month):
    prefix = f"{BRONZE_PREFIX}year={year}/month={month}/"
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".csv.gz"):
                keys.append(obj["Key"])
    return sorted(keys)


def read_csv_gz(s3, key):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    with gzip.open(io.BytesIO(obj["Body"].read()), "rt") as f:
        df = pd.read_csv(f)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)
    return df


def write_parquet(s3, df, year, month):
    key = f"{SILVER_PREFIX}year={year}/month={month}/readings_{year}{month}.parquet"
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    buf.seek(0)
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    logger.info("Wrote %d rows to s3://%s/%s", len(df), BUCKET, key)


def main():
    s3 = boto3.client("s3")
    watermark = get_silver_watermark(s3)
    logger.info("Silver watermark: %r", watermark)

    new_files = list_new_bronze_files(s3, watermark)
    if not new_files:
        logger.info("No new bronze files to process")
        return

    affected = set(partition_from_key(k) for k in new_files)
    logger.info("Affected partitions: %s", affected)

    for year, month in sorted(affected):
        bronze_keys = list_all_bronze_for_partition(s3, year, month)
        frames = [read_csv_gz(s3, k) for k in bronze_keys]
        df = (pd.concat(frames, ignore_index=True)
                .drop_duplicates(subset=["timestamp"])
                .sort_values("timestamp"))
        # Athena TIMESTAMP doesn't support tz-aware values — strip to naive UTC
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
        write_parquet(s3, df, year, month)

    s3.put_object(
        Bucket=BUCKET,
        Key=SILVER_WATERMARK_KEY,
        Body=json.dumps({"last_key": new_files[-1]}).encode()
    )
    logger.info("Silver watermark updated to %s", new_files[-1])


if __name__ == "__main__":
    main()
