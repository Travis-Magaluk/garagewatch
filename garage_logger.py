#!/usr/bin/env python3

import time
import board
import busio
import adafruit_sht31d
import csv
from datetime import datetime
import os
import shutil

# === CONFIG ===
BASE_DIR = "/home/travismagaluk/garagewatch"
CSV_FILE = os.path.join(BASE_DIR, "humidity_log.csv")
LOG_FILE = os.path.join(BASE_DIR, "logger.log")
BACKUP_DIR = os.path.join(BASE_DIR, "log_archive")

# === Setup Directories ===
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# === Archive Existing CSV Log ===
if os.path.exists(CSV_FILE):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"humidity_log_{timestamp}.csv"
    shutil.move(CSV_FILE, os.path.join(BACKUP_DIR, backup_name))

# === Setup I2C Sensor ===
i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_sht31d.SHT31D(i2c)

# === Create New CSV with Headers ===
with open(CSV_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "temperature_C", "humidity_percent"])

print("Logging SHT-30 sensor data. Press Ctrl+C to stop.\n")

# === Logging Loop ===
try:
    while True:
        try:
            temperature = sensor.temperature
            humidity = sensor.relative_humidity
            timestamp = datetime.now().isoformat()

            print(f"{timestamp} - Temp: {temperature:.2f}°C, Humidity: {humidity:.2f}%")

            with open(CSV_FILE, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, f"{temperature:.2f}", f"{humidity:.2f}"])
        except Exception as e:
            print(f"[WARN] Sensor read failed at {datetime.now().isoformat()}: {e}")

        time.sleep(60)

except KeyboardInterrupt:
    print("\nLogging stopped. Final log written.")
