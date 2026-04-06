#!/usr/bin/env python3

import time
import board
import busio
import adafruit_sht31d
import psycopg2
from datetime import datetime
import os
from dotenv import load_dotenv
import alerter

load_dotenv()

# === CONFIG ===
LOG_FILE = "/home/travismagaluk/garagewatch/logger.log"

DB_CONFIG = {
    "host": "localhost",
    "dbname": "garage_data",
    "user": "garage_user",
    "password": "Bl1ssF@ncy!"
}

def write_log(message):
    now = datetime.now().isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(f"{now} - {message}\n")

def connect_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        return conn
    except Exception as e:
        write_log(f"❌ Failed to connect to DB: {e}")
        return None

def init_sensor():
    while True:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            sensor = adafruit_sht31d.SHT31D(i2c)
            write_log("✅ Sensor initialized.")
            return sensor
        except Exception as e:
            write_log(f"⚠️ Sensor init failed, retrying in 5s: {e}")
            time.sleep(5)

print("Logging sensor data to PostgreSQL. Press Ctrl+C to stop.\n")
write_log("🚀 Logger started.")

sensor = init_sensor()

conn = connect_db()
cur = conn.cursor() if conn else None

try:
    while True:
        try:
            # Reconnect if needed
            if conn is None or conn.closed:
                conn = connect_db()
                cur = conn.cursor() if conn else None

            if cur:
                temperature_c = sensor.temperature
                temperature_f = (temperature_c * 9/5) + 32
                humidity = sensor.relative_humidity
                timestamp = datetime.now()

                print(f"{timestamp.isoformat()} - {temperature_f:.2f}°F, {humidity:.2f}%")

                cur.execute(
                    """
                    INSERT INTO readings (timestamp, temperature_c, temperature_f, humidity_percent)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (timestamp, temperature_c, temperature_f, humidity)
                )
                alerter.check_and_alert(conn, write_log)
            else:
                write_log("⚠️ No DB cursor — skipping insert")

        except Exception as e:
            write_log(f"[WARN] Sensor or DB insert failed: {e}")

        time.sleep(1800)  # 30 minutes

except KeyboardInterrupt:
    print("\nLogging stopped. Final entry written.")
    write_log("🛑 Logger stopped by user.")
    if cur: cur.close()
    if conn: conn.close()
