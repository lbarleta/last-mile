# LastMile

Hourly bike-share warehouse and Streamlit dashboard, built on open [GBFS](https://github.com/NABSA/gbfs) feeds.

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What it does

1. **Collect** — pull station and free-bike status from Bay Wheels GBFS once per hour into SQLite
2. **Live Ops** — headline supply balance and walk-shed coverage, KPIs (with prior-hour deltas), regional availability mix chart
3. **Map** — station map colored by empty / low / healthy / full
4. **Trends** — availability trends, station status mix and per-station reliability, estimated bike utilization by hour and weekday
5. **Forecast** *(under development — hidden from the dashboard)* — per-station probability of running empty or full in the next 6 hours, with a rolling-origin backtest against naive baselines

```text
GBFS ──► scripts/collect.py ──┐
                              ├─► data/lastmile-sf.db ──► Streamlit (read-only)
Open-Meteo ──► weather ───────┤
                              │
              scripts/forecast.py (train / backtest / score)
```

Models are trained and scored offline; the dashboard only reads stored predictions.

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

## Stockout forecast (under development)

The pipeline below works end to end, but the **Forecast** view is currently
hidden from the dashboard while the presentation is reworked. Re-enable it by
adding `"Forecast"` back to the options list in
[`app/main.py`](app/main.py); the view and its dispatch branch are still in place.

Predicts, for every station and each of the next six hours, the probability it
will be **empty** (no bikes to take) or **full** (no docks to return to) — the
proactive counterpart to the Live Ops problematic-stations table.

```bash
# One-time: pull historical weather for the span of your snapshots
python scripts/backfill_weather.py

# Backtest, fit, and score the latest snapshot
python scripts/forecast.py --all
```

Hourly, after `collect.py`:

```bash
python scripts/backfill_weather.py --refresh   # recent + forecast hours
python scripts/forecast.py --score             # reuse the saved model
```

Refit periodically (weekly is plenty) with `python scripts/forecast.py --train --backtest`.

Two gradient-boosted classifiers (one per failure mode) take the horizon as an
input feature, so a single model covers all six hours. Inputs are the station's
current occupancy and its recent history, calendar context, weather at the
target hour, and the station's own trailing stockout rate for that hour of day.

Every run is scored against two references on held-out folds — **persistence**
("assume nothing changes") and **climatology** (the station's own rate at that
hour over the last four weeks) — and the results are shown in the dashboard
rather than hidden in a notebook.

## Run the dashboard

```bash
streamlit run app/main.py
```

Opens on **Live Ops**; use the top control for **Map** and **Trends**.
Optional: `export LASTMILE_DB=/path/to/your.db` (not shown in the UI).

Live Ops leads with two headline metrics. **Bikes per 10 docks** is fleet
posture: rideable bikes (docked plus free-floating) against open docks. It sits
in a narrow band and follows a daily cycle — bike-heavy overnight, leanest in
the late afternoon — so it is compared with the same hour over the past four
weeks rather than with the prior hour, which makes a departure from the normal
rhythm visible instead of the rhythm itself. **Coverage** is the rider-facing
counterpart: the share of San Francisco within a 300 m walk of an available
bike. Neither says anything about local imbalance; the problematic-stations
table covers that.

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
| `weather` | Hourly San Francisco weather from Open-Meteo (archive + forecast) |
| `forecast_stockout` | Per-station empty/full probabilities by forecast horizon |
| `forecast_metrics` | Rolling-origin backtest scores for the model and baselines |
| `forecast_calibration` | Reliability bins behind the calibration chart |

All timestamps are local (`America/Los_Angeles`) hourly keys, which makes joins
across these tables direct.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [General Bikeshare Feed Specification (GBFS)](https://github.com/NABSA/gbfs)
- [Bay Wheels](https://www.lyft.com/bikes/bay-wheels) open data
