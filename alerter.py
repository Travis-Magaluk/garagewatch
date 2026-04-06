#!/usr/bin/env python3

import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

HUMIDITY_THRESHOLD = 30.0      # percent
ROLLING_WINDOW_HOURS = 0.05
COOLDOWN_HOURS = 12

_last_alert_sent = None


def _get_rolling_avg(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT AVG(humidity_percent)
            FROM readings
            WHERE timestamp > NOW() - INTERVAL '%s hours';
            """,
            (ROLLING_WINDOW_HOURS,)
        )
        result = cur.fetchone()
    return float(result[0]) if result and result[0] is not None else None


def _send_email(avg_humidity):
    email_from = os.environ["ALERT_EMAIL_FROM"]
    email_to = os.environ["ALERT_EMAIL_TO"]
    app_password = os.environ["ALERT_EMAIL_APP_PASSWORD"]

    msg = EmailMessage()
    msg["Subject"] = "GarageWatch Alert: High Humidity"
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(
        f"Garage humidity has been elevated.\n\n"
        f"  {ROLLING_WINDOW_HOURS}-hour rolling average: {avg_humidity:.1f}%\n"
        f"  Threshold: {HUMIDITY_THRESHOLD}%\n"
        f"  Detected at: {datetime.now().isoformat()}\n\n"
        f"Check the garage for moisture issues."
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(email_from, app_password)
        smtp.send_message(msg)


def check_and_alert(conn, write_log):
    global _last_alert_sent

    avg = _get_rolling_avg(conn)
    if avg is None:
        return

    write_log(f"[ALERT CHECK] {ROLLING_WINDOW_HOURS}h avg humidity: {avg:.1f}%")

    if avg <= HUMIDITY_THRESHOLD:
        return

    now = datetime.now()
    if _last_alert_sent and (now - _last_alert_sent) < timedelta(hours=COOLDOWN_HOURS):
        write_log(f"[ALERT] Threshold exceeded ({avg:.1f}%) but cooldown active — skipping email")
        return

    try:
        _send_email(avg)
        _last_alert_sent = now
        write_log(f"[ALERT] Email sent — {ROLLING_WINDOW_HOURS}h avg humidity {avg:.1f}% exceeds {HUMIDITY_THRESHOLD}%")
    except Exception as e:
        write_log(f"[ALERT] Failed to send email: {e}")
