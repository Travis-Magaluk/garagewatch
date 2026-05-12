# Setup — running the pipeline yourself

Reproduction guide for the Pi-side and AWS-side pieces of the pipeline. Reading this end-to-end will take longer than skimming the README; that's intentional — this is the "I actually want to stand it up" path.

## Hardware

| Item | Notes |
|---|---|
| Raspberry Pi (any model with I2C and Linux) | Tested on a Pi 4 running 32-bit Raspbian. 64-bit Raspberry Pi OS recommended for new builds — avoids the [PyArrow blocker](learnings/pyarrow-32bit.md). |
| Adafruit SHT31D temperature/humidity sensor | I2C address `0x44` by default. |
| Four jumper wires | SDA, SCL, 3V3, GND. |

### Wiring

| SHT31D pin | Pi pin (BCM) | Pi pin (physical) |
|---|---|---|
| VIN | 3V3 | 1 |
| GND | GND | 6 |
| SDA | GPIO 2 / SDA1 | 3 |
| SCL | GPIO 3 / SCL1 | 5 |

Enable I2C with `sudo raspi-config` → Interface Options → I2C. Verify with `i2cdetect -y 1` — the sensor should appear at `0x44`.

## Pi software

```bash
# System packages
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql i2c-tools git

# Clone and set up the project
git clone git@github.com:Travis-Magaluk/garagewatch.git
cd garagewatch
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### Postgres

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE garage_data;
CREATE USER garage_user WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE garage_data TO garage_user;
\c garage_data
CREATE TABLE readings (
    timestamp        TIMESTAMP NOT NULL,
    temperature_c    NUMERIC(5,2),
    temperature_f    NUMERIC(5,2),
    humidity_percent NUMERIC(5,2)
);
CREATE INDEX readings_timestamp_idx ON readings (timestamp);
GRANT INSERT, SELECT ON readings TO garage_user;
```

### Environment

Create `.env` at the repo root:

```
DB_HOST=localhost
DB_NAME=garage_data
DB_USER=garage_user
DB_PASSWORD=...

# Alerter (optional)
ALERT_EMAIL_FROM=...@gmail.com
ALERT_EMAIL_TO=...@gmail.com
ALERT_EMAIL_APP_PASSWORD=...      # Gmail app password, not the account password

# AWS (only needed for the S3 export job on the Pi)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

### Run the logger by hand

```bash
./venv/bin/python scripts/garage_logger.py
```

You should see a reading logged once per minute and one row appearing in the database. `Ctrl-C` stops it.

### systemd unit

Once the manual run works, install a systemd unit so the logger comes up on boot and restarts on crash. Create `/etc/systemd/system/garage_logger.service`:

```ini
[Unit]
Description=GarageWatch sensor logger
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=travismagaluk
WorkingDirectory=/home/travismagaluk/garagewatch
EnvironmentFile=/home/travismagaluk/garagewatch/.env
ExecStart=/home/travismagaluk/garagewatch/venv/bin/python scripts/garage_logger.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable garage_logger
sudo systemctl start garage_logger
sudo systemctl status garage_logger
journalctl -u garage_logger -f      # tail the logs
```

### Daily bronze export

Add a cron entry to run [`scripts/export_to_s3.py`](../scripts/export_to_s3.py) daily at midnight:

```bash
crontab -e
```

```
0 0 * * * cd /home/travismagaluk/garagewatch && ./venv/bin/python scripts/export_to_s3.py >> /home/travismagaluk/garagewatch/logs/export.cron.log 2>&1
```

## AWS

Minimum services: S3, Glue, Athena, IAM. Region used here is `us-east-1` — adjust accordingly.

### S3

Create one bucket, e.g. `garagewatch-data`, with these prefixes (they're created lazily by the scripts; no need to pre-create directories):

```
s3://garagewatch-data/raw/readings/year=YYYY/month=MM/   ← bronze
s3://garagewatch-data/silver/readings/year=YYYY/month=MM/ ← silver
s3://garagewatch-data/athena-results/                     ← Athena workgroup output
s3://garagewatch-data/watermark.json                      ← bronze watermark
s3://garagewatch-data/silver_watermark.json               ← silver watermark
```

### Glue + Athena

Create a Glue database called `garagewatch_raw` and a table over the silver Parquet files:

```sql
CREATE EXTERNAL TABLE garagewatch_raw.readings (
    timestamp         TIMESTAMP,
    temperature_c     DOUBLE,
    temperature_f     DOUBLE,
    humidity_percent  DOUBLE
)
PARTITIONED BY (year STRING, month STRING)
STORED AS PARQUET
LOCATION 's3://garagewatch-data/silver/readings/';

MSCK REPAIR TABLE garagewatch_raw.readings;
```

`MSCK REPAIR` discovers the Hive partitions. Re-run it whenever a new month's partition first appears (or use a Glue crawler on a schedule).

Create a second Glue database `garagewatch_analytics` — dbt writes the mart tables here.

### CI/CD AWS role

The dbt workflow uses OIDC to assume a role in your AWS account. Create an IAM role with:

- **Trust policy** allowing `token.actions.githubusercontent.com` to assume it, scoped to your repo and `main` branch.
- **Permissions** for S3 (read/write on the bucket), Glue (catalog access), and Athena (workgroup access).

Add the role ARN to GitHub repo secrets as `AWS_ROLE_ARN`. The full workflow is [`.github/workflows/dbt.yml`](../.github/workflows/dbt.yml); see [`docs/cicd.md`](cicd.md) for the rationale.

### Tailscale

If you also want CI/CD deploys to the Pi:

1. Install Tailscale on the Pi (`curl -fsSL https://tailscale.com/install.sh | sh`, then `sudo tailscale up`).
2. In the Tailscale admin console, create an OAuth client with `tag:ci` write access.
3. Add `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `PI_SSH_HOST`, and `PI_SSH_KEY` to GitHub repo secrets.

The `deploy.yml` workflow then SSHes to the Pi over the tailnet.

## Quick reference

```bash
# SSH to the Pi (Tailscale hostname)
ssh travismagaluk@garagepi.<tailnet>.ts.net

# Connect to the local database
psql -U garage_user -d garage_data -h localhost

# Tail the logger
journalctl -u garage_logger -f

# Re-run today's bronze export (idempotent — watermark prevents duplicates)
./venv/bin/python scripts/export_to_s3.py
```
