#!/usr/bin/env python3
"""
Incremental export from Pi Postgres to S3 as gzipped CSV.

Watermark pattern:
  1. Read last exported timestamp from S3
  2. Query only rows newer than the watermark
  3. Write as gzipped CSV with Hive partitioning (year=YYYY/month=MM)
  4. Update watermark to max timestamp in this batch

Emits gzipped CSV instead of Parquet because 32-bit Python on this Pi has no
pyarrow wheels. A cloud-side transform converts raw CSV to Parquet under
s3://garagewatch-data/curated/readings/ (medallion bronze → silver).
"""

import csv
import gzip
import json
import logging
import logging.handlers
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import boto3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = "garagewatch-data"
WATERMARK_KEY = "watermark.json"
CSV_PREFIX = "raw/readings"
CSV_HEADER = ["timestamp", "temperature_c", "temperature_f", "humidity_percent"]

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "dbname": os.getenv("DB_NAME", "garage_data"),
    "user": os.getenv("DB_USER", "garage_user"),
    "password": os.getenv("DB_PASSWORD"),
}


def _setup_logging():
    log_format = "%(asctime)s %(levelname)s %(message)s"
    handlers = [logging.StreamHandler()]

    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    handlers.append(
        logging.handlers.RotatingFileHandler(
            log_dir / "export_to_s3.log",
            maxBytes=1_000_000,
            backupCount=3,
        )
    )

    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers)


log = logging.getLogger(__name__)


def get_watermark(s3):
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=WATERMARK_KEY)
        data = json.loads(obj["Body"].read())
        return data["last_exported_timestamp"]
    except s3.exceptions.NoSuchKey:
        log.warning("No watermark found — first run, exporting all rows.")
        return "1970-01-01T00:00:00"


def update_watermark(s3, new_timestamp):
    body = json.dumps({"last_exported_timestamp": new_timestamp})
    s3.put_object(Bucket=S3_BUCKET, Key=WATERMARK_KEY, Body=body)


def fetch_rows(watermark_ts):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except psycopg2.OperationalError as e:
        log.error("Could not connect to database: %s", e)
        raise

    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, temperature_c, temperature_f, humidity_percent
        FROM readings
        WHERE timestamp > %s
        ORDER BY timestamp
        """,
        (watermark_ts,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def partition_rows(rows):
    """Group rows by (year, month) for Hive-style partitioning."""
    partitions = defaultdict(list)
    for row in rows:
        ts = row[0]
        key = (ts.year, ts.month)
        partitions[key].append(row)
    return partitions


def write_to_s3(s3, rows):
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    partitions = partition_rows(rows)

    with tempfile.TemporaryDirectory() as tmpdir:
        for (year, month), part_rows in partitions.items():
            filename = f"readings_{now_str}.csv.gz"
            local_path = os.path.join(tmpdir, filename)

            with gzip.open(local_path, "wt", newline="", encoding="utf-8") as gz:
                writer = csv.writer(gz)
                writer.writerow(CSV_HEADER)
                for ts, temp_c, temp_f, humidity in part_rows:
                    writer.writerow([ts.isoformat(), temp_c, temp_f, humidity])

            s3_key = f"{CSV_PREFIX}/year={year}/month={month:02d}/{filename}"
            try:
                s3.upload_file(local_path, S3_BUCKET, s3_key)
                log.info("Uploaded %s (%d rows)", s3_key, len(part_rows))
            except Exception as e:
                log.error("Failed to upload %s: %s", s3_key, e)
                raise


def main():
    _setup_logging()

    if not os.getenv("DB_PASSWORD"):
        raise EnvironmentError("DB_PASSWORD environment variable is not set")

    s3 = boto3.client("s3")

    log.info("Reading watermark...")
    watermark = get_watermark(s3)
    log.info("Last exported: %s", watermark)

    log.info("Fetching rows from Postgres...")
    rows = fetch_rows(watermark)
    log.info("Rows fetched: %d", len(rows))

    if not rows:
        log.info("Nothing to export. Exiting.")
        return

    log.info("Writing to S3...")
    write_to_s3(s3, rows)

    latest_ts = max(r[0] for r in rows)
    update_watermark(s3, latest_ts.isoformat())
    log.info("Watermark updated to: %s", latest_ts.isoformat())
    log.info("Export complete.")


if __name__ == "__main__":
    main()
