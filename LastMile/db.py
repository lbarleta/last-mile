"""
Read-only query helpers for the LastMile dashboard.

Runs against MySQL through :mod:`LastMile.engine`. Snapshot hours are stored as
a real ``ts`` column but cross this module's public API as
``YYYY-MM-DD-HH:00`` strings, which is what the app, its cache keys, and the
metric layer already speak.

``station_status`` is now keyed on ``(station_id, ts)``, so a snapshot hour
holds exactly one row per station. The aggregate queries used to defend against
duplicates with an inner ``GROUP BY``/``MAX`` pass; that is no longer needed and
the queries are correspondingly cheaper.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, Optional

import pandas as pd

from .config import (
    BACKUP_STATION_RADIUS_M,
    DEFAULT_TIMEZONE,
    LOW_STATION_BIKE_SHARE,
    OPS_DAY_HOUR_END,
    OPS_DAY_HOUR_START,
    PROBLEMATIC_LOOKBACK_HOURS,
    TIMESTAMP_FORMAT,
)
from .engine import (
    Db,
    as_url,
    date_expr,
    hour_expr,
    hour_label_expr,
    key_expr,
    make_engine,
    real_cast,
    to_dt,
    to_key,
)
from .schema import ensure_indexes as _ensure_indexes

# Free-floating bikes have coordinates but no region, and are overwhelmingly
# concentrated in San Francisco, so they are all attributed there.
FREE_FLOATING_REGION = "San Francisco"


def _status_counts(prefix: str = "") -> str:
    """
    Four mutually exclusive station states.

    Ordered so they sum to the station count: a station with neither bikes nor
    docks is counted empty, not both.
    """
    bikes = f"{prefix}num_bikes_available"
    docks = f"{prefix}num_docks_available"
    share = real_cast(bikes)
    return f"""
            SUM(CASE WHEN {bikes} = 0 THEN 1 ELSE 0 END)
                AS empty_stations,
            SUM(CASE WHEN {bikes} > 0 AND {docks} = 0
                     THEN 1 ELSE 0 END) AS full_stations,
            SUM(CASE WHEN {bikes} > 0 AND {docks} > 0
                      AND {share} / ({bikes} + {docks})
                          < {LOW_STATION_BIKE_SHARE}
                     THEN 1 ELSE 0 END) AS low_stations,
            SUM(CASE WHEN {bikes} > 0 AND {docks} > 0
                      AND {share} / ({bikes} + {docks})
                          >= {LOW_STATION_BIKE_SHARE}
                     THEN 1 ELSE 0 END) AS healthy_stations"""


def connect(db_path: Optional[str] = None) -> Db:
    """Open a connection to the configured database, or to an explicit URL."""
    return Db(make_engine(as_url(db_path)).connect())


def ensure_indexes(conn: Db) -> None:
    """Create indexes used by dashboard historical queries."""
    _ensure_indexes(conn)


def list_regions(conn: Db) -> list[str]:
    """Distinct station regions, most stations first."""
    rows = conn.fetchall(
        """
        SELECT COALESCE(region, 'Unknown') AS region, COUNT(*) AS n
        FROM stations
        GROUP BY region
        ORDER BY n DESC
        """
    )
    return [row[0] for row in rows if row[0]]


def get_latest_timestamp(conn: Db) -> Optional[str]:
    row = conn.fetchone("SELECT MAX(ts) FROM station_status")
    return to_key(row[0]) if row and row[0] is not None else None


def get_timestamp_bounds(conn: Db) -> tuple[Optional[str], Optional[str]]:
    row = conn.fetchone("SELECT MIN(ts), MAX(ts) FROM station_status")
    if not row:
        return None, None
    return to_key(row[0]), to_key(row[1])


def list_snapshot_dates(conn: Db) -> list[str]:
    """Distinct calendar dates (YYYY-MM-DD) that have station_status snapshots."""
    day = date_expr("ts")
    rows = conn.fetchall(
        f"""
        SELECT DISTINCT {day} AS d
        FROM station_status
        ORDER BY d
        """
    )
    return [row[0] for row in rows if row[0]]


def list_snapshot_hours_for_date(conn: Db, date_str: str) -> list[str]:
    """
    Hours available for a calendar date.

    Returns hour labels like '15:00'.
    """
    label = hour_label_expr("ts")
    day = date_expr("ts")
    rows = conn.fetchall(
        f"""
        SELECT DISTINCT {label} AS h
        FROM station_status
        WHERE {day} = ?
        ORDER BY h
        """,
        (date_str,),
    )
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
    start = to_dt(latest) - timedelta(hours=hours)
    return start.strftime(TIMESTAMP_FORMAT)


def get_station_snapshot_at(conn: Db, timestamp: str) -> pd.DataFrame:
    """Stations joined with station_status for a specific hourly timestamp."""
    key = key_expr("st.ts")
    return conn.read_sql(
        f"""
        SELECT
            s.station_id,
            s.name,
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
            st.is_renting,
            st.is_installed,
            {key} AS timestamp
        FROM stations s
        INNER JOIN station_status st
            ON s.station_id = st.station_id
        WHERE st.ts = ?
        """,
        (to_dt(timestamp),),
    )


def get_latest_station_snapshot(conn: Db) -> pd.DataFrame:
    """Stations joined with the most recent station_status row."""
    latest = get_latest_timestamp(conn)
    if latest is None:
        return pd.DataFrame()
    return get_station_snapshot_at(conn, latest)


def previous_hour_timestamp(timestamp: str) -> str:
    """Return the previous hourly snapshot key for a timestamp string."""
    return (to_dt(timestamp) - timedelta(hours=1)).strftime(TIMESTAMP_FORMAT)


def is_ops_day_hour(timestamp: str) -> bool:
    """True if timestamp falls in the daytime ops window (7:00–20:00 local)."""
    hour = int(timestamp[11:13])
    return OPS_DAY_HOUR_START <= hour <= OPS_DAY_HOUR_END


def lookback_timestamps(
    timestamp: str, hours: int = PROBLEMATIC_LOOKBACK_HOURS
) -> list[str]:
    """Selected hour plus the previous ``hours - 1`` hourly keys."""
    end = to_dt(timestamp)
    return [
        (end - timedelta(hours=offset)).strftime(TIMESTAMP_FORMAT)
        for offset in range(hours)
    ]


def get_problematic_stations(
    conn: Db,
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

    placeholders = ",".join("?" * len(day_hours))
    df = conn.read_sql(
        f"""
        SELECT
            s.station_id,
            s.name AS name,
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
        WHERE st.ts IN ({placeholders})
        GROUP BY s.station_id, s.name, COALESCE(s.region, 'Unknown')
        HAVING SUM(
            CASE
                WHEN st.num_bikes_available = 0
                  OR st.num_docks_available = 0
                THEN 1 ELSE 0
            END
        ) > 0
        ORDER BY hours_problematic DESC, name ASC
        """,
        tuple(to_dt(ts) for ts in day_hours),
    )
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
    conn: Db,
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
    conn: Db,
    timestamp: str,
    low_range_meters: int = 5000,
) -> Dict[str, int]:
    """Counts from free_bike_status / bike_status for a snapshot hour."""
    row = conn.fetchone(
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
        WHERE ts = ?
        """,
        (low_range_meters, to_dt(timestamp)),
    )
    if not row:
        return {"total": 0, "disabled": 0, "reserved": 0, "low_range": 0}
    return {
        "total": int(row[0] or 0),
        "disabled": int(row[1] or 0),
        "reserved": int(row[2] or 0),
        "low_range": int(row[3] or 0),
    }


def get_free_bike_snapshot(
    conn: Db, timestamp: Optional[str] = None
) -> pd.DataFrame:
    """Free-range bike locations for a snapshot hour (defaults to latest)."""
    if timestamp is None:
        row = conn.fetchone("SELECT MAX(ts) FROM bike_status")
        timestamp = to_key(row[0]) if row and row[0] is not None else None
    if timestamp is None:
        return pd.DataFrame()

    key = key_expr("ts")
    return conn.read_sql(
        f"""
        SELECT
            bike_id,
            lat,
            lon,
            is_reserved,
            is_disabled,
            vehicle_type_id,
            current_range_meters,
            {key} AS timestamp
        FROM bike_status
        WHERE ts = ?
        """,
        (to_dt(timestamp),),
    )


def _time_filters(
    conn: Db,
    column: str,
    since: Optional[str],
    until: Optional[str],
    hour_of_day: Optional[str],
) -> tuple[list[str], list]:
    """Shared WHERE fragments for the history queries."""
    clauses: list[str] = []
    params: list = []
    if since is not None:
        clauses.append(f"{column} >= ?")
        params.append(to_dt(since))
    if until is not None:
        clauses.append(f"{column} <= ?")
        params.append(to_dt(until))
    if hour_of_day is not None:
        clauses.append(f"{hour_expr(column)} = ?")
        params.append(str(hour_of_day).zfill(2))
    return clauses, params


def get_availability_timeseries(
    conn: Db,
    since: Optional[str] = None,
    region: Optional[str] = None,
    until: Optional[str] = None,
    hour_of_day: Optional[str] = None,
) -> pd.DataFrame:
    """
    Docked availability aggregated by hourly timestamp.

    ``num_bikes_available`` in GBFS already includes e-bikes, so the classic
    count is the difference; reporting both alongside the total would double
    count. ``bikes_available`` stays the docked total for existing callers.
    """
    clauses, params = _time_filters(conn, "st.ts", since, until, hour_of_day)
    if region is not None:
        clauses.append("COALESCE(s.region, 'Unknown') = ?")
        params.append(region)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    key = key_expr("st.ts")
    df = conn.read_sql(
        f"""
        SELECT
            {key} AS timestamp,
            SUM(st.num_bikes_available) AS bikes_available,
            SUM(st.num_ebikes_available) AS ebikes_available,
            SUM(st.num_docks_available) AS docks_available,
            {_status_counts("st.")},
            COUNT(*) AS station_count
        FROM station_status st
        INNER JOIN stations s ON s.station_id = st.station_id
        {where}
        GROUP BY st.ts
        ORDER BY st.ts
        """,
        params,
    )
    if df.empty:
        return df
    df["classic_available"] = (
        df["bikes_available"] - df["ebikes_available"]
    ).clip(lower=0)
    return df


def get_free_bike_timeseries(
    conn: Db,
    since: Optional[str] = None,
    region: Optional[str] = None,
    until: Optional[str] = None,
    hour_of_day: Optional[str] = None,
) -> pd.DataFrame:
    """
    Free-floating bike count per hourly timestamp.

    Free bikes carry no region in GBFS, only coordinates. They are treated as
    San Francisco inventory, which is where practically all of them sit, so
    region breakdowns need no spatial join.
    """
    if region is not None and region != FREE_FLOATING_REGION:
        return pd.DataFrame(columns=["timestamp", "free_floating"])

    clauses, params = _time_filters(conn, "ts", since, until, hour_of_day)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    key = key_expr("ts")
    return conn.read_sql(
        f"""
        SELECT {key} AS timestamp, COUNT(*) AS free_floating
        FROM bike_status
        {where}
        GROUP BY ts
        ORDER BY ts
        """,
        params,
    )


def _shift_timestamp(timestamp: str, hours: int) -> str:
    """Shift a snapshot key by a whole number of hours."""
    return (to_dt(timestamp) + timedelta(hours=hours)).strftime(TIMESTAMP_FORMAT)


def get_problematic_timeseries(
    conn: Db,
    since: Optional[str] = None,
    region: Optional[str] = None,
    lookback_hours: int = PROBLEMATIC_LOOKBACK_HOURS,
) -> pd.DataFrame:
    """
    Stations flagged under the Live Ops problematic rule, per snapshot hour.

    A station counts as empty (resp. full) at ``T`` if it was empty (full) in
    any of the trailing ``lookback_hours`` that fall inside the daytime ops
    window. Night hours therefore contribute nothing to the lookback, matching
    ``get_problematic_stations``.
    """
    pad_since = (
        _shift_timestamp(since, -(lookback_hours - 1)) if since is not None else None
    )
    clauses: list[str] = []
    params: list = []
    if pad_since is not None:
        clauses.append("st.ts >= ?")
        params.append(to_dt(pad_since))
    if region is not None:
        clauses.append("COALESCE(s.region, 'Unknown') = ?")
        params.append(region)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    key = key_expr("st.ts")
    flags = conn.read_sql(
        f"""
        SELECT
            {key} AS timestamp,
            st.station_id AS station_id,
            CASE WHEN st.num_bikes_available = 0 THEN 1 ELSE 0 END AS is_empty,
            CASE WHEN st.num_docks_available = 0 THEN 1 ELSE 0 END AS is_full
        FROM station_status st
        INNER JOIN stations s ON s.station_id = st.station_id
        {where}
        """,
        params,
    )
    empty = pd.DataFrame(
        columns=["timestamp", "empty_stations", "full_stations", "station_count"]
    )
    if flags.empty:
        return empty

    base = flags[["station_id", "timestamp"]].copy()
    empty_any = pd.Series(False, index=base.index)
    full_any = pd.Series(False, index=base.index)
    for lag in range(lookback_hours):
        lagged = flags[["station_id", "timestamp", "is_empty", "is_full"]].copy()
        if lag:
            lagged["timestamp"] = lagged["timestamp"].map(
                lambda t, h=lag: _shift_timestamp(t, h)
            )
        merged = base.merge(lagged, on=["station_id", "timestamp"], how="left")
        lookback_ts = base["timestamp"].map(lambda t, h=lag: _shift_timestamp(t, -h))
        ops = lookback_ts.map(is_ops_day_hour)
        empty_any = empty_any | (merged["is_empty"].fillna(0).astype(bool) & ops)
        full_any = full_any | (merged["is_full"].fillna(0).astype(bool) & ops)

    base["empty_flag"] = empty_any.astype(int)
    base["full_flag"] = full_any.astype(int)
    grouped = (
        base.groupby("timestamp", as_index=False)
        .agg(
            empty_stations=("empty_flag", "sum"),
            full_stations=("full_flag", "sum"),
            station_count=("station_id", "count"),
        )
        .sort_values("timestamp")
    )
    if since is not None:
        grouped = grouped[grouped["timestamp"] >= since]
    return grouped.reset_index(drop=True)


def get_station_reliability(
    conn: Db,
    since: Optional[str] = None,
    region: Optional[str] = None,
    min_hours: int = 24,
) -> pd.DataFrame:
    """
    Share of observed hours each station spent empty or full.

    Empty takes precedence over full for the rare hour with neither bikes nor
    docks, matching how the states are counted everywhere else.
    """
    clauses: list[str] = []
    params: list = []
    if since is not None:
        clauses.append("st.ts >= ?")
        params.append(to_dt(since))
    if region is not None:
        clauses.append("COALESCE(s.region, 'Unknown') = ?")
        params.append(region)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(min_hours)

    df = conn.read_sql(
        f"""
        SELECT
            st.station_id AS station_id,
            s.name AS name,
            COALESCE(s.region, 'Unknown') AS region,
            s.capacity AS capacity,
            COUNT(*) AS hours,
            SUM(CASE WHEN st.num_bikes_available = 0 THEN 1 ELSE 0 END)
                AS hours_empty,
            SUM(CASE WHEN st.num_bikes_available > 0
                      AND st.num_docks_available = 0
                     THEN 1 ELSE 0 END) AS hours_full
        FROM station_status st
        INNER JOIN stations s ON s.station_id = st.station_id
        {where}
        GROUP BY st.station_id, s.name, COALESCE(s.region, 'Unknown'), s.capacity
        HAVING COUNT(*) >= ?
        """,
        params,
    )
    if df.empty:
        return df
    df["pct_empty"] = df["hours_empty"] / df["hours"] * 100.0
    df["pct_full"] = df["hours_full"] / df["hours"] * 100.0
    df["pct_failure"] = df["pct_empty"] + df["pct_full"]
    return df.sort_values("pct_failure", ascending=False)


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
