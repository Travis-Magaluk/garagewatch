# Dashboards

Grafana is the visualization layer. It runs as a single Docker Compose service ([`grafana/docker-compose.yml`](../grafana/docker-compose.yml)) with two provisioned datasources and one provisioned dashboard, all in version control.

## What runs

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
    environment:
      - GF_INSTALL_PLUGINS=grafana-athena-datasource
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-data:/var/lib/grafana
      - ./provisioning:/etc/grafana/provisioning
```

A few choices worth flagging:

- **`GF_INSTALL_PLUGINS=grafana-athena-datasource`** — Athena isn't a built-in datasource; the plugin is installed declaratively on container start.
- **`extra_hosts: host.docker.internal:host-gateway`** — lets the container reach a Postgres running on the host. Used by the `GarageDB` datasource for current-state panels.
- **`./provisioning:/etc/grafana/provisioning`** — the entire datasource and dashboard configuration is committed to the repo and mounted in. Spinning up a new Grafana instance produces the same dashboards by construction; nothing is configured through the UI.

## Datasources

Two of them, with deliberately different use cases ([`grafana/provisioning/datasources/garage.yaml`](../grafana/provisioning/datasources/garage.yaml)):

| Datasource | Type | Used for |
|---|---|---|
| `GarageDB` | postgres | "Right now" panels — current temperature, current humidity, data freshness, raw counts |
| `GarageAthena` | grafana-athena-datasource | Everything historical and aggregated — daily/monthly ranges, hourly heatmaps, extreme-days tables, streak rankings |

The split is intentional. "Right now" panels only need the latest reading, so fetching them from the Pi's local database is fast — routing them through S3 and Athena would add a noticeable delay and run up query costs for no benefit. Historical panels crunch hundreds of thousands of readings at once, which would be too slow and too taxing for the Pi to handle on its own.

## Dashboard — `GarageWatch`

One provisioned dashboard ([`grafana/provisioning/dashboards/garage_dashboard.json`](../grafana/provisioning/dashboards/garage_dashboard.json)) with the following panels:

| Panel | Datasource | Source model / query |
|---|---|---|
| Current Temperature | `GarageDB` | Latest row from `readings` |
| Current Humidity | `GarageDB` | Latest row from `readings` |
| Data Freshness | `GarageDB` | `now() - MAX(timestamp)` from `readings` |
| Total Readings | `GarageDB` | `COUNT(*)` from `readings` |
| Temperature & Humidity Over Time | `GarageAthena` | `stg_readings` (raw time series) |
| Rolling Averages (7-day & 30-day) | `GarageAthena` | Window aggregate over `stg_readings` |
| Daily Temperature Range (Min / Avg / Max) | `GarageAthena` | [`daily_summary`](dbt-models.md#daily_summary) |
| Daily Humidity Range (Min / Avg / Max) | `GarageAthena` | [`daily_summary`](dbt-models.md#daily_summary) |
| Avg Temperature by Hour × Month (need to fix) | `GarageAthena` | [`hourly_profile`](dbt-models.md#hourly_profile) |
| Avg Humidity by Hour × Month (need to fix) | `GarageAthena` | [`hourly_profile`](dbt-models.md#hourly_profile) |
| Coldest 15 Days (Last Year) | `GarageAthena` | [`extreme_days`](dbt-models.md#extreme_days) where `category = 'coldest'` |
| Most Humid 15 Days (Last Year) | `GarageAthena` | [`extreme_days`](dbt-models.md#extreme_days) where `category = 'most_humid'` |
| Longest High-Humidity Streaks (≥60%, ≥1 hr) (need to fix) | `GarageAthena` | [`humidity_streaks`](dbt-models.md#humidity_streaks) |

Every historical panel reads from a gold mart, never from raw or staging data. Because the results are pre-computed and stored as tables, Grafana just reads the answer; it doesn't redo all the math on every page load.

## Running it locally

```bash
cd grafana
# Set these in a .env file or your shell, then:
export GRAFANA_ADMIN_PASSWORD=...   # default: admin
export DB_PASSWORD=...               # Pi Postgres password
export ATHENA_ACCESS_KEY_ID=...
export ATHENA_SECRET_ACCESS_KEY=...
docker compose up -d
```

Then open `http://localhost:3000` and log in with username `admin` and the password you set for `GRAFANA_ADMIN_PASSWORD`. The `GarageWatch` dashboard appears automatically under the `GarageWatch` folder.

## Roadmap

- Fix panels that are not working properly. 
- **Annotations on the time-series panel** for sensor restarts and alert firings. Currently the time-series shows the data but not the events that explain anomalies.
- **A weather overlay.** The garage temperature and humidity correlate strongly with outdoor weather; overlaying NWS or Open-Meteo data would turn the dashboard into a story about insulation.
- **An "incident timeline" panel** built from the `humidity_streaks` mart — most useful as a strip plot of streak start/end ranges over the last year.
