"""Read-only SQLite query helpers for the LastMile dashboard."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .config import DEFAULT_DB_PATH, DEFAULT_TIMEZONE, TIMESTAMP_FORMAT


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a read-oriented SQLite connection."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes used by dashboard historical queries."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_station_status_ts "
        "ON station_status(timestamp)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_station_status_station_ts "
        "ON station_status(station_id, timestamp)"
    )
    conn.commit()


def _station_name_expr(conn: sqlite3.Connection) -> str:
    """Support legacy `name_x` column and corrected `name` column."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(stations)")}
    if "name" in cols:
        return "s.name"
    if "name_x" in cols:
        return "s.name_x"
    return "s.station_id"


def get_latest_timestamp(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(timestamp) FROM station_status").fetchone()
    return row[0] if row and row[0] is not None else None


def get_timestamp_bounds(conn: sqlite3.Connection) -> tuple[Optional[str], Optional[str]]:
    row = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM station_status"
    ).fetchone()
    if not row:
        return None, None
    return row[0], row[1]


def list_snapshot_dates(conn: sqlite3.Connection) -> list[str]:
    """Distinct calendar dates (YYYY-MM-DD) that have station_status snapshots."""
    rows = conn.execute(
        """
        SELECT DISTINCT substr(timestamp, 1, 10) AS d
        FROM station_status
        ORDER BY d
        """
    ).fetchall()
    return [row[0] for row in rows if row[0]]


def list_snapshot_hours_for_date(conn: sqlite3.Connection, date_str: str) -> list[str]:
    """
    Hours available for a calendar date.

    Returns hour labels like '15:00' for timestamps matching YYYY-MM-DD-HH:00.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT substr(timestamp, 12, 5) AS h
        FROM station_status
        WHERE substr(timestamp, 1, 10) = ?
        ORDER BY h
        """,
        (date_str,),
    ).fetchall()
    return [row[0] for row in rows if row[0]]


def cutoff_timestamp(
    hours: Optional[int],
    timezone: str = DEFAULT_TIMEZONE,
    latest: Optional[str] = None,
) -> Optional[str]:
    """Return a timestamp string for filtering the last N hours from `latest`."""
    if hours is None:
        return None
    if latest is None:
        raise ValueError("latest timestamp required when filtering by hours")
    dt = datetime.strptime(latest, TIMESTAMP_FORMAT).replace(
        tzinfo=ZoneInfo(timezone)
    )
    start = dt - timedelta(hours=hours)
    return start.strftime(TIMESTAMP_FORMAT)


def get_station_snapshot_at(
    conn: sqlite3.Connection, timestamp: str
) -> pd.DataFrame:
    """Stations joined with station_status for a specific hourly timestamp."""
    name_col = _station_name_expr(conn)
    query = f"""
        SELECT
            s.station_id,
            {name_col} AS name,
            s.short_name,
            s.region_id,
            s.capacity,
            s.lat,
            s.lon,
            s.region,
            st.num_bikes_available,
            st.num_docks_available,
            st.num_ebikes_available,
            st.num_docks_disabled,
            st.num_bikes_disabled,
            st.timestamp
        FROM stations s
        INNER JOIN station_status st
            ON s.station_id = st.station_id
        WHERE st.timestamp = ?
    """
    return pd.read_sql_query(query, conn, params=(timestamp,))


def get_latest_station_snapshot(conn: sqlite3.Connection) -> pd.DataFrame:
    """Stations joined with the most recent station_status row."""
    latest = get_latest_timestamp(conn)
    if latest is None:
        return pd.DataFrame()
    return get_station_snapshot_at(conn, latest)


def previous_hour_timestamp(timestamp: str) -> str:
    """Return the previous hourly snapshot key for a timestamp string."""
    dt = datetime.strptime(timestamp, TIMESTAMP_FORMAT) - timedelta(hours=1)
    return dt.strftime(TIMESTAMP_FORMAT)


def get_free_bike_counts(
    conn: sqlite3.Connection,
    timestamp: str,
    low_range_meters: int = 5000,
) -> Dict[str, int]:
    """Counts from free_bike_status / bike_status for a snapshot hour."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN is_disabled = 1 THEN 1 ELSE 0 END) AS disabled,
            SUM(CASE WHEN is_reserved = 1 THEN 1 ELSE 0 END) AS reserved,
            SUM(
                CASE
                    WHEN current_range_meters IS NOT NULL
                         AND current_range_meters <= ?
                    THEN 1 ELSE 0
                END
            ) AS low_range
        FROM bike_status
        WHERE timestamp = ?
        """,
        (low_range_meters, timestamp),
    ).fetchone()
    if not row:
        return {"total": 0, "disabled": 0, "reserved": 0, "low_range": 0}
    return {
        "total": int(row[0] or 0),
        "disabled": int(row[1] or 0),
        "reserved": int(row[2] or 0),
        "low_range": int(row[3] or 0),
    }


def get_free_bike_snapshot(
    conn: sqlite3.Connection, timestamp: Optional[str] = None
) -> pd.DataFrame:
    """Free-range bike locations for a snapshot hour (defaults to latest)."""
    if timestamp is None:
        row = conn.execute("SELECT MAX(timestamp) FROM bike_status").fetchone()
        timestamp = row[0] if row else None
    if timestamp is None:
        return pd.DataFrame()

    return pd.read_sql_query(
        """
        SELECT
            bike_id,
            lat,
            lon,
            is_reserved,
            is_disabled,
            vehicle_type_id,
            current_range_meters,
            timestamp
        FROM bike_status
        WHERE timestamp = ?
        """,
        conn,
        params=(timestamp,),
    )


def get_availability_timeseries(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
) -> pd.DataFrame:
    """System-wide availability aggregated by hourly timestamp."""
    clauses = []
    params: list = []
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT
            timestamp,
            SUM(num_bikes_available) AS bikes_available,
            SUM(num_ebikes_available) AS ebikes_available,
            SUM(num_docks_available) AS docks_available,
            SUM(CASE WHEN num_bikes_available = 0 THEN 1 ELSE 0 END) AS empty_stations,
            SUM(CASE WHEN num_docks_available = 0 THEN 1 ELSE 0 END) AS full_stations,
            COUNT(*) AS station_count
        FROM station_status
        {where}
        GROUP BY timestamp
        ORDER BY timestamp
    """
    return pd.read_sql_query(query, conn, params=params)


def get_station_status_history(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
) -> pd.DataFrame:
    """
    Per-station status rows for pattern analysis.

    Prefer get_availability_timeseries for system charts; use this only when
    station-level history is required and the window is bounded.
    """
    clauses = []
    params: list = []
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT
            station_id,
            num_bikes_available,
            num_docks_available,
            num_ebikes_available,
            timestamp
        FROM station_status
        {where}
    """
    return pd.read_sql_query(query, conn, params=params)


def get_utilization_snapshot(conn: sqlite3.Connection) -> pd.DataFrame:
    """Latest snapshot with utilization = bikes / (bikes + docks)."""
    df = get_latest_station_snapshot(conn)
    if df.empty:
        return df
    capacity_proxy = df["num_bikes_available"] + df["num_docks_available"]
    df = df.copy()
    df["utilization"] = df["num_bikes_available"] / capacity_proxy.replace(0, pd.NA)
    return df


def avg_distance_to_nearest_station_m(
    stations: pd.DataFrame,
    free_bikes: pd.DataFrame,
) -> Optional[float]:
    """
    Average haversine distance (meters) from each free-floating bike
    to its nearest station. Vectorized; cheap at Bay Wheels scale.
    """
    import numpy as np

    if stations.empty or free_bikes.empty:
        return None

    st = stations.dropna(subset=["lat", "lon"])
    bk = free_bikes.copy()
    bk["lat"] = pd.to_numeric(bk["lat"], errors="coerce")
    bk["lon"] = pd.to_numeric(bk["lon"], errors="coerce")
    bk = bk.dropna(subset=["lat", "lon"])
    if st.empty or bk.empty:
        return None

    st_lat = np.radians(st["lat"].to_numpy(dtype=float))[None, :]
    st_lon = np.radians(st["lon"].to_numpy(dtype=float))[None, :]
    bk_lat = np.radians(bk["lat"].to_numpy(dtype=float))[:, None]
    bk_lon = np.radians(bk["lon"].to_numpy(dtype=float))[:, None]

    dlat = st_lat - bk_lat
    dlon = st_lon - bk_lon
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(bk_lat) * np.cos(st_lat) * np.sin(dlon / 2) ** 2
    )
    dist_m = 2 * 6_371_000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return float(dist_m.min(axis=1).mean())
