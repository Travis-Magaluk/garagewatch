#!/usr/bin/env python3
"""
Incremental export from Pi Postgres to S3 Parquet.

Watermark pattern:
  1. Read last exported timestamp from S3
  2. Query only rows newer than the watermark
  3. Write as Parquet with Hive partitioning (year=YYYY/month=MM)
  4. Update watermark to max timestamp in this batch
"""

import json
import logging
import logging.handlers
import os
import tempfile
from datetime import datetime
from pathlib import Path

import boto3
import psycopg2
import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = "garagewatch-data"
WATERMARK_KEY = "watermark.json"
PARQUET_PREFIX = "raw/readings"

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


def rows_to_arrow_table(rows):
    timestamps, temp_c, temp_f, humidity = zip(*rows)
    table = pa.table({
        "timestamp":        pa.array(timestamps, type=pa.timestamp("us")),
        "temperature_c":    pa.array(temp_c,     type=pa.float64()),
        "temperature_f":    pa.array(temp_f,     type=pa.float64()),
        "humidity_percent": pa.array(humidity,   type=pa.float64()),
    })
    # Add partition columns for Hive-style layout (year=YYYY/month=MM)
    ts_col = table.column("timestamp")
    table = table.append_column("year",  pa.array([str(t.as_py().year) for t in ts_col]))
    table = table.append_column("month", pa.array([str(t.as_py().month).zfill(2) for t in ts_col]))
    return table


def write_to_s3(s3, table):
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    with tempfile.TemporaryDirectory() as tmpdir:
        pq.write_to_dataset(
            table,
            root_path=tmpdir,
            partition_cols=["year", "month"],
        )
        for dirpath, _, filenames in os.walk(tmpdir):
            for filename in filenames:
                if not filename.endswith(".parquet"):
                    continue
                local_path = os.path.join(dirpath, filename)
                relative = os.path.relpath(local_path, tmpdir)
                s3_key = f"{PARQUET_PREFIX}/{relative.replace('part-0.parquet', f'readings_{now_str}.parquet')}"
                try:
                    s3.upload_file(local_path, S3_BUCKET, s3_key)
                    log.info("Uploaded %s", s3_key)
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

    table = rows_to_arrow_table(rows)

    log.info("Writing to S3...")
    write_to_s3(s3, table)

    latest_ts = max(r[0] for r in rows)
    update_watermark(s3, latest_ts.isoformat())
    log.info("Watermark updated to: %s", latest_ts.isoformat())
    log.info("Export complete.")


if __name__ == "__main__":
    main()
