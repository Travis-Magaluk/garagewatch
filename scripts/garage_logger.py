#!/usr/bin/env python3

import logging
import logging.handlers
import os
import time
from datetime import datetime
from pathlib import Path

import adafruit_sht31d
import board
import busio
import psycopg2
from dotenv import load_dotenv

import scripts.alerter as alerter

load_dotenv()

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
            log_dir / "garage_logger.log",
            maxBytes=1_000_000,
            backupCount=3,
        )
    )

    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers)


log = logging.getLogger(__name__)


def connect_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        return conn
    except psycopg2.OperationalError as e:
        log.error("Failed to connect to DB: %s", e)
        return None


def init_sensor():
    while True:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            sensor = adafruit_sht31d.SHT31D(i2c)
            log.info("Sensor initialized.")
            return sensor
        except Exception as e:
            log.warning("Sensor init failed, retrying in 5s: %s", e)
            time.sleep(5)


if not os.getenv("DB_PASSWORD"):
    raise EnvironmentError("DB_PASSWORD environment variable is not set")

_setup_logging()
log.info("Logger started.")

sensor = init_sensor()
conn = connect_db()
cur = conn.cursor() if conn else None

try:
    while True:
        try:
            if conn is None or conn.closed:
                conn = connect_db()
                cur = conn.cursor() if conn else None

            if cur:
                temperature_c = sensor.temperature
                temperature_f = (temperature_c * 9/5) + 32
                humidity = sensor.relative_humidity
                timestamp = datetime.now()

                log.info("%.2f°F, %.2f%%", temperature_f, humidity)

                cur.execute(
                    """
                    INSERT INTO readings (timestamp, temperature_c, temperature_f, humidity_percent)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (timestamp, temperature_c, temperature_f, humidity)
                )
                alerter.check_and_alert(conn)
            else:
                log.warning("No DB cursor — skipping insert")

        except Exception as e:
            log.warning("Sensor or DB insert failed: %s", e)

        time.sleep(1800)

except KeyboardInterrupt:
    log.info("Logger stopped by user.")
    if cur:
        cur.close()
    if conn:
        conn.close()
