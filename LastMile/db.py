"""Read-only SQLite query helpers for the LastMile dashboard."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .config import (
    DEFAULT_DB_PATH,
    DEFAULT_TIMEZONE,
    BACKUP_STATION_RADIUS_M,
    OPS_DAY_HOUR_END,
    OPS_DAY_HOUR_START,
    PROBLEMATIC_LOOKBACK_HOURS,
    TIMESTAMP_FORMAT,
)


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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bike_status_ts ON bike_status(timestamp)"
    )
    conn.commit()


def list_regions(conn: sqlite3.Connection) -> list[str]:
    """Distinct station regions, most stations first."""
    rows = conn.execute(
        """
        SELECT COALESCE(region, 'Unknown') AS region, COUNT(*) AS n
        FROM stations
        GROUP BY region
        ORDER BY n DESC
        """
    ).fetchall()
    return [row[0] for row in rows if row[0]]


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


def is_ops_day_hour(timestamp: str) -> bool:
    """True if timestamp falls in the daytime ops window (7:00–20:00 local)."""
    hour = int(timestamp[11:13])
    return OPS_DAY_HOUR_START <= hour <= OPS_DAY_HOUR_END


def lookback_timestamps(timestamp: str, hours: int = PROBLEMATIC_LOOKBACK_HOURS) -> list[str]:
    """Selected hour plus the previous ``hours - 1`` hourly keys."""
    end = datetime.strptime(timestamp, TIMESTAMP_FORMAT)
    return [
        (end - timedelta(hours=offset)).strftime(TIMESTAMP_FORMAT)
        for offset in range(hours)
    ]


def get_problematic_stations(
    conn: sqlite3.Connection,
    timestamp: str,
    *,
    lookback_hours: int = PROBLEMATIC_LOOKBACK_HOURS,
    backup_radius_m: float = BACKUP_STATION_RADIUS_M,
) -> pd.DataFrame:
    """
    Stations that were empty or full in the lookback window.

    Only daytime ops hours (7:00–20:00) count. Night snapshots in the window
    are ignored. Ordered by hours spent empty/full (desc).

    Also suggests the nearest non-problematic backup station within
    ``backup_radius_m`` (default 900 m).
    """
    candidates = lookback_timestamps(timestamp, lookback_hours)
    day_hours = [ts for ts in candidates if is_ops_day_hour(ts)]
    empty_cols = [
        "station_id",
        "name",
        "region",
        "hours_problematic",
        "hours_empty",
        "hours_full",
        "issue",
        "backup_station",
        "backup_distance_m",
    ]
    if not day_hours:
        return pd.DataFrame(columns=empty_cols)

    name_col = _station_name_expr(conn)
    placeholders = ",".join("?" * len(day_hours))
    query = f"""
        SELECT
            s.station_id,
            {name_col} AS name,
            COALESCE(s.region, 'Unknown') AS region,
            SUM(
                CASE
                    WHEN st.num_bikes_available = 0
                      OR st.num_docks_available = 0
                    THEN 1 ELSE 0
                END
            ) AS hours_problematic,
            SUM(
                CASE WHEN st.num_bikes_available = 0 THEN 1 ELSE 0 END
            ) AS hours_empty,
            SUM(
                CASE WHEN st.num_docks_available = 0 THEN 1 ELSE 0 END
            ) AS hours_full
        FROM station_status st
        INNER JOIN stations s
            ON s.station_id = st.station_id
        WHERE st.timestamp IN ({placeholders})
        GROUP BY s.station_id, {name_col}, COALESCE(s.region, 'Unknown')
        HAVING hours_problematic > 0
        ORDER BY hours_problematic DESC, name ASC
    """
    df = pd.read_sql_query(query, conn, params=tuple(day_hours))
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    def _issue(row: pd.Series) -> str:
        empty = int(row["hours_empty"]) > 0
        full = int(row["hours_full"]) > 0
        if empty and full:
            return "Empty & full"
        if empty:
            return "Empty"
        return "Full"

    df["issue"] = df.apply(_issue, axis=1)
    return _attach_backup_stations(conn, df, timestamp, backup_radius_m)


def _haversine_m(
    lat1: "np.ndarray",
    lon1: "np.ndarray",
    lat2: "np.ndarray",
    lon2: "np.ndarray",
):
    import numpy as np

    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    )
    return 2 * 6_371_000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _attach_backup_stations(
    conn: sqlite3.Connection,
    problematic: pd.DataFrame,
    timestamp: str,
    backup_radius_m: float,
) -> pd.DataFrame:
    """Nearest non-problematic station within radius, if any."""
    import numpy as np

    snapshot = get_station_snapshot_at(conn, timestamp)
    if snapshot.empty:
        out = problematic.copy()
        out["backup_station"] = None
        out["backup_distance_m"] = None
        return out

    locs = snapshot[["station_id", "name", "lat", "lon"]].copy()
    locs["lat"] = pd.to_numeric(locs["lat"], errors="coerce")
    locs["lon"] = pd.to_numeric(locs["lon"], errors="coerce")
    locs = locs.dropna(subset=["lat", "lon"])

    problem_ids = set(problematic["station_id"].astype(str))
    candidates = locs[~locs["station_id"].astype(str).isin(problem_ids)].copy()

    out = problematic.copy()
    backups: list[Optional[str]] = []
    distances_m: list[Optional[float]] = []

    if candidates.empty:
        out["backup_station"] = None
        out["backup_distance_m"] = None
        return out

    cand_lat = candidates["lat"].to_numpy(dtype=float)
    cand_lon = candidates["lon"].to_numpy(dtype=float)
    cand_names = candidates["name"].astype(str).to_numpy()

    loc_by_id = locs.set_index(locs["station_id"].astype(str))

    for station_id in out["station_id"].astype(str):
        if station_id not in loc_by_id.index:
            backups.append(None)
            distances_m.append(None)
            continue
        row = loc_by_id.loc[station_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        dist_m = _haversine_m(
            np.array([float(row["lat"])]),
            np.array([float(row["lon"])]),
            cand_lat,
            cand_lon,
        )
        within = dist_m <= backup_radius_m
        if not np.any(within):
            backups.append(None)
            distances_m.append(None)
            continue
        idx = int(np.argmin(np.where(within, dist_m, np.inf)))
        backups.append(cand_names[idx])
        distances_m.append(float(dist_m[idx]))

    out["backup_station"] = backups
    out["backup_distance_m"] = distances_m
    return out


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
    region: Optional[str] = None,
) -> pd.DataFrame:
    """
    Docked availability aggregated by hourly timestamp.

    ``num_bikes_available`` in GBFS already includes e-bikes, so the classic
    count is the difference; reporting both alongside the total would double
    count. ``bikes_available`` stays the docked total for existing callers.
    """
    clauses = []
    params: list = []
    if since is not None:
        clauses.append("st.timestamp >= ?")
        params.append(since)
    if region is not None:
        clauses.append("COALESCE(s.region, 'Unknown') = ?")
        params.append(region)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # Join and deduplicate unconditionally: the collector appends without a
    # uniqueness constraint, so an unjoined COUNT(*) overstates the fleet and
    # would not equal the sum of the regions.
    query = f"""
        SELECT
            timestamp,
            SUM(num_bikes_available) AS bikes_available,
            SUM(num_ebikes_available) AS ebikes_available,
            SUM(num_docks_available) AS docks_available,
            SUM(CASE WHEN num_bikes_available = 0 THEN 1 ELSE 0 END) AS empty_stations,
            SUM(CASE WHEN num_docks_available = 0 THEN 1 ELSE 0 END) AS full_stations,
            COUNT(*) AS station_count
        FROM (
            SELECT
                st.timestamp AS timestamp,
                st.station_id AS station_id,
                MAX(st.num_bikes_available) AS num_bikes_available,
                MAX(st.num_ebikes_available) AS num_ebikes_available,
                MAX(st.num_docks_available) AS num_docks_available
            FROM station_status st
            INNER JOIN stations s ON s.station_id = st.station_id
            {where}
            GROUP BY st.timestamp, st.station_id
        )
        GROUP BY timestamp
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, params=params)
    if df.empty:
        return df
    df["classic_available"] = (
        df["bikes_available"] - df["ebikes_available"]
    ).clip(lower=0)
    return df


def _nearest_station_regions(
    conn: sqlite3.Connection, lat: "np.ndarray", lon: "np.ndarray"
) -> "np.ndarray":
    """Region of the closest station to each coordinate."""
    import numpy as np

    stations = pd.read_sql_query(
        """
        SELECT COALESCE(region, 'Unknown') AS region, lat, lon
        FROM stations
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        """,
        conn,
    )
    if stations.empty:
        return np.full(len(lat), "Unknown", dtype=object)

    st_lat = np.radians(stations["lat"].to_numpy(dtype=float))[None, :]
    st_lon = np.radians(stations["lon"].to_numpy(dtype=float))[None, :]
    regions = stations["region"].to_numpy()

    out = np.empty(len(lat), dtype=object)
    # Chunked so the pairwise matrix stays small regardless of input size.
    for start in range(0, len(lat), 4096):
        end = start + 4096
        pt_lat = np.radians(lat[start:end])[:, None]
        pt_lon = np.radians(lon[start:end])[:, None]
        dlat = st_lat - pt_lat
        dlon = st_lon - pt_lon
        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(pt_lat) * np.cos(st_lat) * np.sin(dlon / 2) ** 2
        )
        out[start:end] = regions[np.argmin(a, axis=1)]
    return out


def get_free_bike_timeseries(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
    region: Optional[str] = None,
) -> pd.DataFrame:
    """
    Free-floating bike count per hourly timestamp.

    Free bikes carry no region, so when one is requested each bike is credited
    to its nearest station's region. Coordinates are rounded to ~100 m first,
    which collapses millions of rows into a few thousand distinct locations.
    """
    clauses = []
    params: list = []
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    if region is None:
        return pd.read_sql_query(
            f"""
            SELECT timestamp, COUNT(*) AS free_floating
            FROM bike_status
            {where}
            GROUP BY timestamp
            ORDER BY timestamp
            """,
            conn,
            params=params,
        )

    cells = pd.read_sql_query(
        f"""
        SELECT timestamp,
               ROUND(lat, 3) AS lat_r,
               ROUND(lon, 3) AS lon_r,
               COUNT(*) AS n
        FROM bike_status
        {where}
        GROUP BY timestamp, lat_r, lon_r
        """,
        conn,
        params=params,
    )
    if cells.empty:
        return pd.DataFrame(columns=["timestamp", "free_floating"])

    cells = cells.dropna(subset=["lat_r", "lon_r"])
    unique = cells[["lat_r", "lon_r"]].drop_duplicates()
    unique["region"] = _nearest_station_regions(
        conn,
        unique["lat_r"].to_numpy(dtype=float),
        unique["lon_r"].to_numpy(dtype=float),
    )
    merged = cells.merge(unique, on=["lat_r", "lon_r"], how="left")
    merged = merged[merged["region"] == region]
    if merged.empty:
        return pd.DataFrame(columns=["timestamp", "free_floating"])

    return (
        merged.groupby("timestamp", as_index=False)["n"]
        .sum()
        .rename(columns={"n": "free_floating"})
        .sort_values("timestamp")
    )


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


def get_utilization_snapshot(
    conn: sqlite3.Connection, region: Optional[str] = None
) -> pd.DataFrame:
    """Latest snapshot with utilization = bikes / (bikes + docks)."""
    df = get_latest_station_snapshot(conn)
    if df.empty:
        return df
    df = df.copy()
    if region is not None:
        df = df[df["region"].fillna("Unknown") == region]
        if df.empty:
            return df
    capacity_proxy = df["num_bikes_available"] + df["num_docks_available"]
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
