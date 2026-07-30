# Last Mile

Hourly bike-share warehouse and Streamlit dashboard, built on open
[GBFS](https://github.com/NABSA/gbfs) feeds. Currently wired to Bay Wheels
(San Francisco Bay Area).

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What it does

The project has two sides that share one SQLite warehouse.

**Ingest.** A collector pulls station and free-bike status from the Bay Wheels
GBFS feed once an hour and appends it to a local database. Station metadata is
set up once; after that, each run is a cron-friendly snapshot write.

**Dashboard.** A Streamlit app reads that warehouse and presents it in three
views. **Live Ops** surfaces system-wide health for a chosen hour — supply
balance, walk-shed coverage, availability KPIs, problematic stations, and how
status mixes across regions. **Map** places stations and free-floating bikes
geographically, colored by empty, low, healthy, or full. **Trends** follows the
same indicators over time: fleet availability, station failure patterns, and an
estimate of how many bikes are in use through the day and week.

```text
GBFS ──► scripts/collect.py ──► data/lastmile-sf.db ──► Streamlit (read-only)
```

Metric definitions and why particular visualizations were chosen are documented
in [`NOTES.md`](NOTES.md).

## Quick start

```bash
git clone https://github.com/lbarleta/last-mile.git
cd last-mile && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/collect.py --setup   # first time
python scripts/collect.py           # hourly thereafter
streamlit run app/main.py
```

The warehouse lives at `data/lastmile-sf.db` (gitignored). Override with
`LASTMILE_DB` if needed.

## Library usage

```python
from LastMile import LastMileSetup, LastMileManager, LastMileMetrics, DEFAULT_DB_PATH

with LastMileSetup(
    feeds_url="https://gbfs.baywheels.com/gbfs/2.3/gbfs.json",
    lang="en",
    db_path=DEFAULT_DB_PATH,
) as setup:
    setup.create_tables()

with LastMileManager(
    feeds_url="https://gbfs.baywheels.com/gbfs/2.3/gbfs.json",
    lang="en",
    db_path=DEFAULT_DB_PATH,
) as manager:
    manager.update_data()

with LastMileMetrics(db_path=DEFAULT_DB_PATH) as metrics:
    print(metrics.get_live_ops_metrics())
```

See [`LastMile/README.md`](LastMile/README.md) for the package layout and API.

## Project layout

```text
last-mile/
  LastMile/          Python package (ingest + metrics)
  app/               Streamlit dashboard
  scripts/collect.py Hourly GBFS collector
  assets/            SF county boundary for coverage
  data/              Local SQLite warehouse (gitignored)
  NOTES.md           Metric definitions and design choices
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
  the next several hours, trained offline and surfaced as a dashboard view
- **Maintenance tracking in Trends** — graphs for disabled bikes and docks over
  time, so service outages are visible alongside availability
- **Coverage tracking in Trends** — how the San Francisco walk-shed evolves
  hour by hour and day by day, not only at a single Live Ops snapshot

## Acknowledgments

- [General Bikeshare Feed Specification (GBFS)](https://github.com/NABSA/gbfs)
- [Bay Wheels](https://www.lyft.com/bikes/bay-wheels) open data
