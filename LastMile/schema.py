"""
DDL for the LastMile tables.

Two things changed relative to the original SQLite-only schema:

* Snapshot hours are a real ``ts`` DATETIME column instead of
  ``YYYY-MM-DD-HH:00`` text, and every status table has a primary key on
  ``(entity, ts)``. Collection inserts against that key, so re-running the
  collector for an hour is a no-op rather than a second copy. SQLite accepted
  duplicates silently and three hours of history ended up doubled (one from the
  DST fall-back, two from repeated runs), which the query layer had to defend
  against with ``GROUP BY``/``MAX``.
* Column types match what GBFS actually publishes. SQLite coerced
  ``vehicle_type_id`` to integers because the column was declared ``INTEGER``,
  which silently breaks for any system using UUID vehicle types.

DATETIME is deliberate over TIMESTAMP: MySQL converts TIMESTAMP columns to and
from UTC using the session time zone, which would shift the local-time values
this project stores. Identifiers are VARCHAR rather than TEXT because MySQL
cannot put a TEXT column in a primary key without a prefix length; 64 characters
covers the 36-char UUIDs some GBFS publishers use with room to spare.
"""

from __future__ import annotations

from .engine import Db

STATUS_TABLES = ("station_status", "bike_status")


def create_statements() -> list[str]:
    """DDL for every table, safe to run repeatedly."""
    return [
        """
        CREATE TABLE IF NOT EXISTS stations (
            station_id  VARCHAR(64) PRIMARY KEY,
            name        TEXT,
            short_name  TEXT,
            region_id   TEXT,
            capacity    INT,
            lat         DOUBLE,
            lon         DOUBLE,
            region      TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS vehicle_types (
            vehicle_type_id  VARCHAR(64) PRIMARY KEY,
            form_factor      TEXT,
            propulsion_type  TEXT,
            max_range_meters DOUBLE
        )
        """,
        # is_installed / is_renting / is_returning / last_reported are published
        # by GBFS and were previously discarded, which made an out-of-service
        # station indistinguishable from a genuinely empty one.
        """
        CREATE TABLE IF NOT EXISTS station_status (
            station_id           VARCHAR(64) NOT NULL,
            ts                   DATETIME    NOT NULL,
            num_bikes_available  INT,
            num_docks_available  INT,
            num_ebikes_available INT,
            num_docks_disabled   INT,
            num_bikes_disabled   INT,
            is_installed         TINYINT,
            is_renting           TINYINT,
            is_returning         TINYINT,
            last_reported        BIGINT,
            PRIMARY KEY (station_id, ts)
        )
        """,
        # vehicle_type_id stays text: Lyft publishes "1"/"2" but other systems
        # (Spin, Bird) publish UUIDs.
        """
        CREATE TABLE IF NOT EXISTS bike_status (
            bike_id              VARCHAR(64) NOT NULL,
            ts                   DATETIME    NOT NULL,
            lat                  DOUBLE,
            lon                  DOUBLE,
            is_reserved          TINYINT,
            is_disabled          TINYINT,
            vehicle_type_id      TEXT,
            current_range_meters DOUBLE,
            last_reported        BIGINT,
            PRIMARY KEY (bike_id, ts)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS weather (
            ts            DATETIME PRIMARY KEY,
            temp_c        DOUBLE,
            precip_mm     DOUBLE,
            wind_kph      DOUBLE,
            humidity_pct  DOUBLE,
            cloud_pct     DOUBLE,
            source        TEXT NOT NULL,
            fetched_at    TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS forecast_stockout (
            origin_ts     DATETIME    NOT NULL,
            target_ts     DATETIME    NOT NULL,
            horizon       INT         NOT NULL,
            station_id    VARCHAR(64) NOT NULL,
            p_empty       DOUBLE,
            p_full        DOUBLE,
            bikes_now     DOUBLE,
            docks_now     DOUBLE,
            model_version TEXT,
            created_at    TEXT,
            PRIMARY KEY (origin_ts, station_id, horizon)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS forecast_metrics (
            model_version VARCHAR(64) NOT NULL,
            created_at    TEXT,
            fold          INT,
            fold_start    TEXT,
            fold_end      TEXT,
            target        TEXT,
            model         TEXT,
            horizon       INT,
            n_obs         INT,
            base_rate     DOUBLE,
            brier         DOUBLE,
            log_loss      DOUBLE,
            avg_precision DOUBLE,
            roc_auc       DOUBLE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS forecast_calibration (
            model_version  VARCHAR(64) NOT NULL,
            created_at     TEXT,
            target         TEXT,
            model          TEXT,
            bin_lower      DOUBLE,
            bin_upper      DOUBLE,
            n_obs          INT,
            mean_predicted DOUBLE,
            observed_rate  DOUBLE
        )
        """,
    ]


# Indexes the dashboard's history queries rely on. The ``(station_id, ts)``
# primary keys already cover per-station lookups, so these only add the
# timestamp-leading access paths.
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("idx_station_status_ts", "station_status", "ts"),
    ("idx_bike_status_ts", "bike_status", "ts"),
    ("idx_forecast_origin", "forecast_stockout", "origin_ts"),
)


def create_all(db: Db, with_indexes: bool = True) -> None:
    """Create every table (and optionally its indexes) if absent."""
    for statement in create_statements():
        db.execute(statement)
    db.commit()
    if with_indexes:
        ensure_indexes(db)


def ensure_indexes(db: Db) -> None:
    """
    Create any missing index.

    Existence is checked rather than declared: MySQL has no
    ``CREATE INDEX IF NOT EXISTS``, so re-running a plain CREATE would error.
    """
    for name, table, columns in INDEXES:
        if name in db.indexes(table):
            continue
        if db.has_table(table):
            db.execute(f"CREATE INDEX {name} ON `{table}`({columns})")
    db.commit()
