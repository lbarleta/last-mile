# Last Mile

Hourly [GBFS](https://github.com/MobilityData/gbfs) collection into a Parquet
warehouse, with a Streamlit dashboard over it. Point it at any system's
`gbfs.json`, on spec 3.0 or 2.3.

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Quick start

```bash
git clone https://github.com/lbarleta/last-mile.git
cd last-mile && python3 -m venv .venv && source .venv/bin/activate
pip install -e .

lastmile init-db      # create the lake, load reference data (asks first)
lastmile collect      # one hourly collection; run from cron
lastmile status       # what the warehouse holds
lastmile dashboard    # serve the Streamlit app
```

Nothing needs configuring to try it: the shipped `lastmile.toml` collects
Austin into `data/lake/austin` and also declares Curitiba. Each GBFS system is
a `[systems.<name>]` table; `--system` on any command picks one and
`default_system` applies otherwise.

```toml
[general]
default_system = "austin"

[systems.austin]
lake_path = "data/lake/austin"
feeds_url = "https://austin.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json"

[systems.curitiba]
lake_path = "data/lake/curitiba"
feeds_url = "https://curitiba.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json"
```

```bash
lastmile collect --system curitiba  # default_system when omitted
```

```cron
5 * * * * cd /path/to/last-mile && .venv/bin/lastmile collect >> logs/collect.log 2>&1
```

`lastmile collect` runs every path: the hourly snapshot, the slow-changing
reference feeds, and the geofencing zones. The latter two cost nothing when
unchanged. `--snapshot`, `--reference` and `--geofencing` run exactly the paths
named instead.

## Warehouse

A directory of Parquet files read by DuckDB in-process. No server, no
credentials, no connection string; moving a warehouse is copying the directory.

```text
data/lake/
  station_status/2026-10-29.parquet       hourly history, one file per UTC day
  station_information/data.parquet        current state
  station_information_log/data.parquet    one row per add / change / removal
```

Tables are named for the GBFS feeds they hold and columns for the fields in
them, under 3.0 names. Two kinds of feed, two shapes:

| Shape | Tables | Written |
| --- | --- | --- |
| Snapshotted | `station_status`, `station_vehicle_types_available`, `station_vehicle_docks_available`, `vehicle_status` | appended once per collection run, partitioned by day |
| Tracked | `system_information`, `gbfs_versions`, `system_regions`, `system_pricing_plans`, `system_alerts`, `vehicle_types`, `station_information` | current state, plus a `_log` row whenever an entity is added, changed or removed |

Geofencing zones are collected but are not a table: zones have no ids in GBFS
and nothing reads them live, so each version of the collection is archived as
one standalone GeoJSON document — `geofencing_zones/<timestamp>.geojson`, the
newest file being current — written only when the feed's content changed, with
geometry exactly as published. Open one directly in QGIS or
`geopandas.read_file`.

Collection is idempotent: re-running an hour that is already stored adds
nothing. Writes land as a file rename, so the collector can append while the
dashboard reads.

Not collected: per-vehicle `rental_uris`.

Read the lake without this package:

```bash
duckdb -c "SELECT ts, SUM(num_vehicles_available) FROM 'data/lake/station_status/*.parquet'
           GROUP BY ts ORDER BY ts"
```

## Feeds

`lastmile.gbfs` reads 2.3 and 3.0 and returns the 3.0 shape. It handles the
discovery envelope (`data.<lang>.feeds` vs `data.feeds`), the renamed feeds
(`free_bike_status` → `vehicle_status`) and fields (`num_bikes_available` →
`num_vehicles_available`, `bike_id` → `vehicle_id`), localized `{text,
language}` names, RFC 3339 timestamps, and boolean flags. The spec version is
read from the discovery document, or inferred from its shape when absent.

Timezone, display name and spec version come from the system's own
`system_information` feed and are stored in `system_information`. The timezone
is what the dashboard renders hours in; see [Timestamps](#timestamps).

GBFS has no electric-vehicle count; it is derived by joining
`station_vehicle_types_available` to `vehicle_types.propulsion_type`.

## Dashboard

Three views. **Live Ops**: system health for a chosen hour — supply balance,
walk-shed coverage, availability KPIs, problematic stations, status by region.
**Map**: stations and free-floating vehicles, colored empty / low / healthy /
full. **Trends**: the same indicators over time. Metric definitions are in
[`NOTES.md`](NOTES.md).

## Configuration

One file, `lastmile.toml`, found at or above the working directory or wherever
`LASTMILE_CONFIG` points; that variable is the only thing read from the
environment. Every key is optional except a system's `lake_path` and
`feeds_url`, and defaults for the rest are on `Settings` in
`src/lastmile/settings.py`.

- `[general]`: `default_system`, `request_timeout_s`, `umami_website_id`.
- `[systems.<name>]`: what differs between bike-share systems — `lake_path`,
  `feeds_url`, `feeds_lang`, `timezone`, `dashboard_title`,
  `boundary_geojson`, `projected_crs`. A system's table is self-contained;
  nothing is inherited from another.
- `[metrics]`: thresholds and windows, shared by every system.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

No network and no server: feed tests run against recorded GBFS documents in
`tests/fixtures/gbfs/`, warehouse tests build a lake in a tmp directory.

## Not implemented

`lastmile weather` and `lastmile forecast`, and the modules behind them
(`weather.py`, `forecasting/`), are stubs — wiring with no logic. The `weather`
table is declared as a placeholder but nothing writes to it, and no forecast
tables exist.

## Timestamps

One rule: **every timestamp is an instant with an explicit timezone.** GBFS
publishes all of its timestamps as RFC 3339, and the lake follows the spec's
lead — every timestamp column (`ts`, `observed_at`, `fetched_at`) is a
`TIMESTAMPTZ`, the collector stamps snapshots with the current UTC hour, and
the storage layer refuses a naive `datetime` outright. Nothing in the lake is
in local time, and neither the collector nor the metrics know what timezone the
system is in.

Local time is a display concern, handled in one place. When a lake is opened,
`lastmile.db.Db` reads the system's `system_information.timezone` (or the
`timezone` setting, which overrides it) and applies it to its DuckDB session,
so the hour labels and dates the dashboard shows are the system's own
wall-clock time. A lake whose system declares no timezone renders UTC and logs
a warning every time it is opened; a system without a timezone is a problem
the operator should know about.

Consequences worth knowing:

- **DST.** UTC has none, so collection is unaffected: the local hour that
  repeats at fall-back is two stored snapshots, and the hour that vanishes at
  spring-forward is simply a label no snapshot carries. Aggregates count both
  fall-back rows. The dashboard's snapshot picker, which works in local labels,
  resolves the one repeated label per year to the later of the two readings and
  skips the earlier one.
- **Partitions** are UTC days, so which file a row lands in never depends on
  the display zone.
- **Half-hour zones** (India, Newfoundland) will show `HH:00` labels for hours
  that start at `:30` on the local clock. Snapshots are still taken on the UTC
  hour.
- **Geofencing captures** are named for their UTC instant, with a trailing `Z`.
- **One system per lake.** The display zone is a property of the lake; run one
  lake per GBFS system.

## Collection cadence

`lastmile collect` stamps each run with the current UTC hour, and the snapshot
key (`YYYY-MM-DD-HH:00`) has no minute field. Running the cron entry more often
than hourly is safe but pointless: the first run of each hour stores a
snapshot, the rest fetch the feed and discard it as a duplicate key. Finer
resolution would mean widening the key format and revisiting the metric
definitions that count stored rows as hours.
