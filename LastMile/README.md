# LastMile

Python package for ingesting GBFS bike-share feeds into SQLite and computing
operations and trend metrics. The Streamlit dashboard in [`app/`](../app/) is a
thin read-only client over this library.

## Layout

```text
LastMile/
  config.py     Defaults (DB path, timezone, ops windows, coverage)
  utils.py      GBFS feed client and shared SQLite connection
  setup.py      One-time stations table / schema (LastMileSetup)
  manager.py    Hourly station + free-bike collection (LastMileManager)
  db.py         Read-only SQL helpers and indexes
  metrics.py    Live Ops and Trends metrics (LastMileMetrics)
  coverage.py   San Francisco walk-shed geometry
```

Hourly collection entry point: [`scripts/collect.py`](../scripts/collect.py).

## Public API

```python
from LastMile import (
    LastMileSetup,
    LastMileManager,
    LastMileMetrics,
    LastMileUtils,
    DEFAULT_FEEDS_URL,
    DEFAULT_LANG,
    DEFAULT_TIMEZONE,
)
```

| Class | Role |
| --- | --- |
| `LastMileSetup` | Create / refresh the `stations` table and schema |
| `LastMileManager` | Append an hourly `station_status` + `bike_status` snapshot |
| `LastMileMetrics` | KPIs, tables, and time series for the dashboard |
| `LastMileUtils` | Low-level GBFS fetch helpers and DB connection |

### Setup and collection

Every class takes an optional `db_path`, a MySQL URL. Leave it out to fall back
to `LASTMILE_DATABASE_URL`, read from the environment or from `.env`.

```python
from LastMile import LastMileSetup, LastMileManager, DEFAULT_FEEDS_URL

with LastMileSetup(feeds_url=DEFAULT_FEEDS_URL, lang="en") as setup:
    setup.create_tables()

with LastMileManager(feeds_url=DEFAULT_FEEDS_URL, lang="en") as manager:
    manager.update_data()
```

### Metrics

```python
from LastMile import LastMileMetrics

with LastMileMetrics() as metrics:
    live = metrics.get_live_ops_metrics()          # latest (or chosen) snapshot
    series = metrics.get_availability_timeseries(hours=24 * 7)
    util = metrics.get_bike_utilization(hours=24 * 28)
```

Common accessors on `LastMileMetrics`:

| Method | Returns |
| --- | --- |
| `get_live_ops_metrics` | Snapshot KPIs, deltas, coverage, station frame |
| `get_problematic_stations` | Stations empty/full in the trailing daytime lookback |
| `get_station_status_by_region` | Empty / low / healthy / full mix by region |
| `get_availability_timeseries` | Hourly fleet split (classic, e-bike, free-floating, docks) |
| `get_bike_utilization` | Estimated bikes in use by hour and weekday |
| `get_problematic_by_hour` | Share of stations flagged under the Live Ops rule |
| `get_station_reliability` | Per-station % of hours empty vs full |

## Conventions

- **Timestamps** are local (`America/Los_Angeles`) hourly keys: `YYYY-MM-DD-HH:00`
- **Regions** come from the stations table; free-floating bikes are attributed to San Francisco
- **Problematic** means empty or full in any of the last three daytime hours (7am–8pm)
- The library opens SQLite read-oriented for metrics; collectors write separately

## Dashboard

```bash
streamlit run app/main.py
```

See the [project README](../README.md) for setup, collection, and product
overview, and [`NOTES.md`](../NOTES.md) for metric definitions and design
choices.
