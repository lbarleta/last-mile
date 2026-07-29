# LastMile

Hourly bike-share warehouse and Streamlit dashboard, built on open [GBFS](https://github.com/NABSA/gbfs) feeds.

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What it does

1. **Collect** — pull station and free-bike status from Bay Wheels GBFS once per hour into SQLite
2. **Live Ops** — KPIs (with prior-hour deltas), regional availability mix chart
3. **Map** — station map colored by empty / low / healthy / full
4. **Historical** — availability trends, peak hours, day-of-week patterns, utilization

```text
GBFS ──► scripts/collect.py ──► data/lastmile-sf.db ──► Streamlit (read-only)
```

## Setup

```bash
git clone https://github.com/yourusername/last-mile.git
cd last-mile
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Place (or collect) the SQLite warehouse at `data/lastmile-sf.db`. The `data/` directory is gitignored and stays local.

## Collect hourly snapshots

```bash
# First-time / recreate station metadata
python scripts/collect.py --setup

# Ongoing hourly run (cron-friendly)
python scripts/collect.py
```

## Run the dashboard

```bash
streamlit run app/main.py
```

Opens on **Live Ops**; use the top control for **Map** and **Historical**. Optional:
`export LASTMILE_DB=/path/to/your.db` (not shown in the UI).

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

## Data model

| Table | Role |
| --- | --- |
| `stations` | Static station info (name, capacity, lat/lon, region) |
| `station_status` | Hourly availability per station (`timestamp` = `YYYY-MM-DD-HH:00`) |
| `bike_status` | Hourly free-bike locations and status |

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [General Bikeshare Feed Specification (GBFS)](https://github.com/NABSA/gbfs)
- [Bay Wheels](https://www.lyft.com/bikes/bay-wheels) open data
