#!/usr/bin/env python3
"""
Load the legacy SQLite warehouse into MySQL.

This is a one-time tool. SQLite appears here only as the format the old data
happens to be in; it is read through the standard library and the application
itself no longer speaks it.

    python scripts/migrate_db.py --dry-run
    python scripts/migrate_db.py --target mysql://user:pw@host/lastmile

What it changes on the way through:

* ``timestamp`` text (``YYYY-MM-DD-HH:00``) becomes a real ``ts`` column.
* One row per ``(station_id, ts)``. Three hours in the existing history hold
  two or eight stacked copies; the extras are collapsed, keeping the highest
  reading per station-hour.
* ``vehicle_type_id`` becomes text, since only Lyft happens to use numeric ids.
* ``stations.name_x`` becomes ``stations.name``.

The source database is opened read-only and never written to.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from LastMile.config import LEGACY_SQLITE_PATH, TIMESTAMP_FORMAT
from LastMile.engine import (
    Db,
    describe,
    make_engine,
    normalize_url,
    resolve_database_url,
)
from LastMile.schema import create_all, ensure_indexes

SQLITE_TS = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate LastMile SQLite -> new schema")
    parser.add_argument(
        "--source", default=LEGACY_SQLITE_PATH, help="legacy SQLite database path"
    )
    parser.add_argument(
        "--target",
        default=None,
        help="target MySQL URL (defaults to LASTMILE_DATABASE_URL)",
    )
    parser.add_argument("--batch-size", type=int, default=200_000)
    parser.add_argument(
        "--tables",
        nargs="*",
        default=None,
        help="subset of tables to copy (default: all present)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be copied without writing",
    )
    return parser.parse_args()


# --- source helpers -------------------------------------------------------


def open_source(path: str) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise SystemExit(f"source database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def source_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def parse_ts(value) -> Optional[datetime]:
    """Legacy keys are ``YYYY-MM-DD-HH:00``; tolerate ISO too."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in (TIMESTAMP_FORMAT, SQLITE_TS, "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


# --- table specifications -------------------------------------------------
# Each entry: target table -> (source SELECT, target columns, ts column indexes)
# The SELECT does the de-duplication so uniqueness is guaranteed before any
# write, rather than relying on conflict handling to silently absorb it.

SPECS: dict[str, dict] = {
    "stations": {
        "select": """
            SELECT station_id,
                   {name_col} AS name,
                   short_name, region_id, capacity, lat, lon, region
            FROM stations
        """,
        "columns": [
            "station_id", "name", "short_name", "region_id",
            "capacity", "lat", "lon", "region",
        ],
        "ts_columns": [],
    },
    "station_status": {
        "select": """
            SELECT station_id,
                   timestamp,
                   MAX(num_bikes_available)  AS num_bikes_available,
                   MAX(num_docks_available)  AS num_docks_available,
                   MAX(num_ebikes_available) AS num_ebikes_available,
                   MAX(num_docks_disabled)   AS num_docks_disabled,
                   MAX(num_bikes_disabled)   AS num_bikes_disabled
            FROM station_status
            GROUP BY station_id, timestamp
        """,
        "columns": [
            "station_id", "ts", "num_bikes_available", "num_docks_available",
            "num_ebikes_available", "num_docks_disabled", "num_bikes_disabled",
        ],
        "ts_columns": [1],
    },
    "bike_status": {
        "select": """
            SELECT bike_id,
                   timestamp,
                   MAX(lat)                  AS lat,
                   MAX(lon)                  AS lon,
                   MAX(is_reserved)          AS is_reserved,
                   MAX(is_disabled)          AS is_disabled,
                   CAST(MAX(vehicle_type_id) AS TEXT) AS vehicle_type_id,
                   MAX(current_range_meters) AS current_range_meters
            FROM bike_status
            GROUP BY bike_id, timestamp
        """,
        "columns": [
            "bike_id", "ts", "lat", "lon", "is_reserved", "is_disabled",
            "vehicle_type_id", "current_range_meters",
        ],
        "ts_columns": [1],
    },
    "weather": {
        "select": """
            SELECT timestamp, temp_c, precip_mm, wind_kph, humidity_pct,
                   cloud_pct, source, fetched_at
            FROM weather
        """,
        "columns": [
            "ts", "temp_c", "precip_mm", "wind_kph", "humidity_pct",
            "cloud_pct", "source", "fetched_at",
        ],
        "ts_columns": [0],
    },
    "forecast_stockout": {
        "select": """
            SELECT origin_timestamp, target_timestamp, horizon, station_id,
                   p_empty, p_full, bikes_now, docks_now, model_version, created_at
            FROM forecast_stockout
        """,
        "columns": [
            "origin_ts", "target_ts", "horizon", "station_id", "p_empty",
            "p_full", "bikes_now", "docks_now", "model_version", "created_at",
        ],
        "ts_columns": [0, 1],
    },
    "forecast_metrics": {
        "select": "SELECT * FROM forecast_metrics",
        "columns": [
            "model_version", "created_at", "fold", "fold_start", "fold_end",
            "target", "model", "horizon", "n_obs", "base_rate", "brier",
            "log_loss", "avg_precision", "roc_auc",
        ],
        "ts_columns": [],
    },
    "forecast_calibration": {
        "select": "SELECT * FROM forecast_calibration",
        "columns": [
            "model_version", "created_at", "target", "model", "bin_lower",
            "bin_upper", "n_obs", "mean_predicted", "observed_rate",
        ],
        "ts_columns": [],
    },
}


def resolve_select(table: str, source: sqlite3.Connection) -> str:
    spec = SPECS[table]
    sql = spec["select"]
    if table == "stations":
        cols = {r[1] for r in source.execute("PRAGMA table_info(stations)")}
        name_col = "name" if "name" in cols else ("name_x" if "name_x" in cols else "station_id")
        sql = sql.format(name_col=name_col)
    return sql


# --- writers --------------------------------------------------------------


def iter_rows(
    source: sqlite3.Connection, sql: str, batch_size: int
) -> Iterator[list[tuple]]:
    cursor = source.execute(sql)
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        yield [tuple(r) for r in rows]


def convert(rows: Sequence[tuple], ts_columns: Sequence[int]) -> list[tuple]:
    if not ts_columns:
        return list(rows)
    out = []
    for row in rows:
        values = list(row)
        for idx in ts_columns:
            values[idx] = parse_ts(values[idx])
        out.append(tuple(values))
    return out


def insert_mysql(engine, table: str, columns: Sequence[str], batches) -> int:
    """
    Bulk load through batched multi-row INSERTs.

    MySQL has no COPY. ``LOAD DATA LOCAL INFILE`` would be faster still but
    needs ``local_infile`` enabled on both client and server, which is not
    something to assume on shared hosting.
    """
    raw = engine.raw_connection()
    total = 0
    try:
        collist = ", ".join(f"`{c}`" for c in columns)
        row_sql = "(" + ", ".join(["%s"] * len(columns)) + ")"
        cur = raw.cursor()
        for rows in batches:
            for chunk in _chunked(rows, 5_000):
                values = ", ".join([row_sql] * len(chunk))
                flat = [v for row in chunk for v in row]
                cur.execute(
                    f"INSERT IGNORE INTO `{table}` ({collist}) VALUES {values}",
                    flat,
                )
                total += len(chunk)
                print(f"    {total:,} rows", end="\r", flush=True)
            raw.commit()
    finally:
        raw.close()
    return total


def _chunked(rows: Sequence[tuple], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def main() -> int:
    args = parse_args()
    target_url = normalize_url(args.target) if args.target else resolve_database_url()

    source = open_source(args.source)
    present = source_tables(source)
    wanted = args.tables or list(SPECS)
    tables = [t for t in wanted if t in SPECS and t in present]
    missing = [t for t in wanted if t not in present]

    print(f"source : {args.source}")
    print(f"target : {describe(target_url)}")
    if missing:
        print(f"skipped (absent in source): {', '.join(missing)}")

    print("\nrow counts and duplicates in source:")
    plan = {}
    for table in tables:
        sql = resolve_select(table, source)
        raw_n = source.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        dedup_n = source.execute(
            f"SELECT COUNT(*) FROM ({sql})"
        ).fetchone()[0]
        plan[table] = (sql, raw_n, dedup_n)
        note = f"   -{raw_n - dedup_n:,} duplicate rows" if raw_n != dedup_n else ""
        print(f"  {table:22s} {raw_n:>10,} -> {dedup_n:>10,}{note}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    engine = make_engine(target_url)
    with engine.connect() as connection:
        create_all(Db(connection), with_indexes=False)
    print("\nschema created")

    for table in tables:
        sql, _, expected = plan[table]
        print(f"  copying {table} ({expected:,} rows)")
        started = time.time()
        batches = (
            convert(rows, SPECS[table]["ts_columns"])
            for rows in iter_rows(source, sql, args.batch_size)
        )
        written = insert_mysql(engine, table, SPECS[table]["columns"], batches)
        print(f"    {written:,} rows in {time.time() - started:.1f}s")

    print("\nbuilding indexes")
    with engine.connect() as connection:
        db = Db(connection)
        ensure_indexes(db)
        for table in tables:
            db.execute(f"ANALYZE TABLE `{table}`")
        db.commit()

    source.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
