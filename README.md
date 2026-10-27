# Last Mile

Hourly bike-share warehouse and Streamlit dashboard, built on open
[GBFS](https://github.com/NABSA/gbfs) feeds. The collector and schema are
meant to be **feed-agnostic** (GBFS 2.3 and 3.0). The dashboard copy and
defaults are still Bay Wheels until that revamp lands.

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What it does

One installable package with two sides sharing one warehouse (MySQL today,
DuckDB planned).

**Ingest.** `lastmile collect` pulls station and free-bike status from the Bay
Wheels GBFS feed once an hour and appends it to the database. Station metadata
is set up once; after that, each run is a cron-friendly snapshot write.

**Dashboard.** A Streamlit app reads that warehouse and presents it in three
views. **Live Ops** surfaces system-wide health for a chosen hour — supply
balance, walk-shed coverage, availability KPIs, problematic stations, and how
status mixes across regions. **Map** places stations and free-floating bikes
geographically, colored by empty, low, healthy, or full. **Trends** follows the
same indicators over time: fleet availability, station failure patterns, and an
estimate of how many bikes are in use through the day and week.

```text
GBFS ──► lastmile collect ──► database ──► Streamlit (read-only)
```

Metric definitions and why particular visualizations were chosen are documented
in [`NOTES.md`](NOTES.md).

## Feed-agnostic development

Future work should treat this repo as a GBFS client, not a Bay Wheels client.
Do not add publisher-specific fields or a single city's geography as defaults.
Read timezone, language, and display name from `system_information`; normalize
v2.3 and v3.0 into one internal model.

The two Austin feeds are the reference pair for development and tests — same
system, both spec versions, so parser and schema changes have to work on both:

- GBFS 2.3: https://austin.publicbikesystem.net/customer/gbfs/v2/gbfs.json
- GBFS 3.0: https://austin.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json

Austin is docked-only (no `free_bike_status` / `vehicle_status`), publishes
empty `system_regions`, mixes bicycles and standing scooters, and uses
`America/Chicago`. GBFS 3 also drops the language envelope on the discovery
document, localizes `name` as `{text, language}` arrays, and renames
`num_bikes_*` to `num_vehicles_*`. Code that only understands Bay Wheels 2.3
will fail on the 3.0 feed.

## Quick start

```bash
git clone https://github.com/lbarleta/last-mile.git
cd last-mile && python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env     # then set LASTMILE_DATABASE_URL

lastmile init-db         # first time: creates tables, loads station metadata
lastmile collect         # hourly thereafter (bootstraps itself if needed)
lastmile status          # what the warehouse holds
lastmile dashboard       # serve the Streamlit app
```

A cron entry needs nothing but the venv's `lastmile` on PATH:

```cron
5 * * * * cd /path/to/last-mile && .venv/bin/lastmile collect >> logs/collect.log 2>&1
```

## Configuration

Three layers, each overriding the one before it:

1. Built-in defaults (the `Settings` class in `src/lastmile/settings.py`).
2. **`lastmile.toml`** at the repo root — tunables you want in git: search
   radii, thresholds, feed URLs, the coverage boundary GeoJSON.
3. **Environment / `.env`** — secrets and host-specific values. Any TOML key
   maps to `LASTMILE_<KEY>` uppercased (`database_url` →
   `LASTMILE_DATABASE_URL`, `coverage_radius_m` → `LASTMILE_COVERAGE_RADIUS_M`).

`LASTMILE_DATABASE_URL` is the one required value. `.env` is read automatically
by every entry point, and real environment variables win over it.

## Library usage

```python
from lastmile import db
from lastmile.metrics import Metrics
from lastmile.collect import collect_snapshot, init_db

conn = db.connect()          # uses LASTMILE_DATABASE_URL
init_db(conn)                # schema + reference data, idempotent
collect_snapshot(conn)       # one hourly snapshot

with Metrics() as metrics:
    print(metrics.get_live_ops_metrics())
```

## Project layout

```text
last-mile/
  lastmile.toml             Tunables (committed); secrets go in .env
  assets/                   City boundary GeoJSON for coverage (user-swappable)
  src/lastmile/
    cli.py                  The `lastmile` command
    settings.py             Config loading; constants.py holds internals
    gbfs.py                 GBFS feed client
    collect.py              Hourly snapshots + reference data
    db/                     Connection wrapper, schema DDL, query layer
    metrics/                Live Ops / Trends / snapshot metrics
    forecasting/            Stockout forecast (under development)
    weather.py              Weather cache (under development)
    dashboard/              Streamlit app (`lastmile dashboard`)
  tests/                    Pytest wiring (fixtures only so far)
  NOTES.md                  Metric definitions and design choices
```

## Data model

| Table | Role |
| --- | --- |
| `stations` | Static station info (name, capacity, lat/lon, region) |
| `station_status` | Hourly availability per station |
| `bike_status` | Hourly free-bike locations and status |

Timestamps are local (`America/Los_Angeles`) hourly keys of the form
`YYYY-MM-DD-HH:00`, which makes joins across tables direct.

## Future plans

- **Stockout forecast** — per-station probability of running empty or full over
  the next several hours (`lastmile forecast`, needs `pip install -e ".[forecast]"`);
  under development alongside the weather cache (`lastmile weather`)
- **DuckDB** — the dialect-specific SQL is isolated in `src/lastmile/db/`
  (marked `DIALECT`) and `db/schema.py`, so the MySQL → DuckDB move stays local
- **Maintenance tracking in Trends** — graphs for disabled bikes and docks over
  time, so service outages are visible alongside availability
- **Coverage tracking in Trends** — how the San Francisco walk-shed evolves
  hour by hour and day by day, not only at a single Live Ops snapshot

## Acknowledgments

- [General Bikeshare Feed Specification (GBFS)](https://github.com/NABSA/gbfs)
- [Bay Wheels](https://www.lyft.com/bikes/bay-wheels) open data
