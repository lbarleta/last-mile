"""San Francisco hourly weather from Open-Meteo, cached in SQLite.

Weather is the strongest exogenous driver of bike-share demand that is not
already implied by the calendar. Two endpoints are used:

* the ERA5 archive for the historical record (it lags real time by ~5 days), and
* the forecast endpoint for the recent gap plus the future hours the stockout
  model scores against.

Both are stored in one ``weather`` table keyed by the same local-time hourly
key used everywhere else (``YYYY-MM-DD-HH:00``), so joins against
``station_status`` need no timezone handling. Archive rows win over forecast
rows for the same hour.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .config import (
    DEFAULT_TIMEZONE,
    OPEN_METEO_ARCHIVE_LAG_DAYS,
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_FORECAST_URL,
    SF_WEATHER_LAT,
    SF_WEATHER_LON,
    TIMESTAMP_FORMAT,
    WEATHER_VARIABLES,
)

SOURCE_ARCHIVE = "archive"
SOURCE_FORECAST = "forecast"

# Open-Meteo variable -> column in the weather table
COLUMN_MAP = {
    "temperature_2m": "temp_c",
    "precipitation": "precip_mm",
    "wind_speed_10m": "wind_kph",
    "relative_humidity_2m": "humidity_pct",
    "cloud_cover": "cloud_pct",
}
WEATHER_COLUMNS = tuple(COLUMN_MAP[name] for name in WEATHER_VARIABLES)


def ensure_weather_table(conn: sqlite3.Connection) -> None:
    """Create the weather cache if it does not exist."""
    columns = ",\n            ".join(f"{col} REAL" for col in WEATHER_COLUMNS)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS weather (
            timestamp TEXT PRIMARY KEY,
            {columns},
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _request(url: str, params: dict) -> pd.DataFrame:
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    hourly = payload.get("hourly")
    if not hourly or not hourly.get("time"):
        return pd.DataFrame()

    df = pd.DataFrame(hourly)
    # Open-Meteo returns local ISO strings ("2026-07-28T14:00") because we ask
    # for the station timezone; reshape into the warehouse's hourly key.
    df["timestamp"] = (
        pd.to_datetime(df["time"], format="ISO8601").dt.strftime(TIMESTAMP_FORMAT)
    )
    df = df.rename(columns=COLUMN_MAP)
    keep = ["timestamp", *[col for col in WEATHER_COLUMNS if col in df.columns]]
    return df[keep]


def fetch_archive(
    start_date: str,
    end_date: str,
    *,
    lat: float = SF_WEATHER_LAT,
    lon: float = SF_WEATHER_LON,
    timezone: str = DEFAULT_TIMEZONE,
    variables: Sequence[str] = WEATHER_VARIABLES,
) -> pd.DataFrame:
    """Hourly ERA5 reanalysis between two ``YYYY-MM-DD`` dates (inclusive)."""
    return _request(
        OPEN_METEO_ARCHIVE_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ",".join(variables),
            "timezone": timezone,
        },
    )


def fetch_forecast(
    *,
    past_days: int = 7,
    forecast_days: int = 3,
    lat: float = SF_WEATHER_LAT,
    lon: float = SF_WEATHER_LON,
    timezone: str = DEFAULT_TIMEZONE,
    variables: Sequence[str] = WEATHER_VARIABLES,
) -> pd.DataFrame:
    """Recent observed hours plus the forecast horizon."""
    return _request(
        OPEN_METEO_FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(variables),
            "past_days": max(0, min(past_days, 92)),
            "forecast_days": max(1, min(forecast_days, 16)),
            "timezone": timezone,
        },
    )


def upsert_weather(
    conn: sqlite3.Connection, df: pd.DataFrame, source: str
) -> int:
    """
    Write weather rows, letting archive values overwrite forecast values.

    A forecast row never replaces an archive row for the same hour, so
    backfilling and hourly refreshes can run in any order.
    """
    if df.empty:
        return 0

    ensure_weather_table(conn)
    cols = [col for col in WEATHER_COLUMNS if col in df.columns]
    fetched_at = datetime.now().isoformat(timespec="seconds")

    placeholders = ", ".join("?" * (len(cols) + 3))
    assignments = ", ".join(f"{col} = excluded.{col}" for col in cols)
    sql = f"""
        INSERT INTO weather (timestamp, {", ".join(cols)}, source, fetched_at)
        VALUES ({placeholders})
        ON CONFLICT(timestamp) DO UPDATE SET
            {assignments},
            source = excluded.source,
            fetched_at = excluded.fetched_at
        WHERE excluded.source = '{SOURCE_ARCHIVE}'
           OR weather.source = '{SOURCE_FORECAST}'
    """
    rows = [
        (row.timestamp, *[getattr(row, col) for col in cols], source, fetched_at)
        for row in df.itertuples(index=False)
    ]
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def _today(timezone: str = DEFAULT_TIMEZONE) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def _date_chunks(
    start: date, end: date, days: int = 365
) -> Iterable[tuple[str, str]]:
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=days - 1), end)
        yield cursor.isoformat(), chunk_end.isoformat()
        cursor = chunk_end + timedelta(days=1)


def backfill(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    *,
    verbose: bool = False,
) -> int:
    """
    Populate the cache for a date range.

    Days older than the ERA5 publication lag come from the archive endpoint;
    anything more recent (plus a short future window) comes from the forecast
    endpoint, which is what the model uses for target-hour weather.
    """
    ensure_weather_table(conn)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    today = _today()
    archive_end = min(end, today - timedelta(days=OPEN_METEO_ARCHIVE_LAG_DAYS))

    written = 0
    if archive_end >= start:
        for chunk_start, chunk_end in _date_chunks(start, archive_end):
            df = fetch_archive(chunk_start, chunk_end)
            written += upsert_weather(conn, df, SOURCE_ARCHIVE)
            if verbose:
                print(f"  archive {chunk_start} → {chunk_end}: {len(df)} hours")

    past_days = max(1, (today - archive_end).days + 1)
    recent = fetch_forecast(past_days=min(past_days, 92))
    written += upsert_weather(conn, recent, SOURCE_FORECAST)
    if verbose:
        print(f"  forecast window (past {min(past_days, 92)}d): {len(recent)} hours")
    return written


def load_weather(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> pd.DataFrame:
    """Cached weather as a DataFrame keyed by hourly timestamp."""
    ensure_weather_table(conn)
    clauses, params = [], []
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until is not None:
        clauses.append("timestamp <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return pd.read_sql_query(
        f"""
        SELECT timestamp, {", ".join(WEATHER_COLUMNS)}, source
        FROM weather
        {where}
        ORDER BY timestamp
        """,
        conn,
        params=params,
    )


def coverage_summary(conn: sqlite3.Connection) -> dict:
    """Row counts and bounds, for CLI reporting."""
    ensure_weather_table(conn)
    row = conn.execute(
        """
        SELECT COUNT(*), MIN(timestamp), MAX(timestamp),
               SUM(CASE WHEN source = 'archive' THEN 1 ELSE 0 END)
        FROM weather
        """
    ).fetchone()
    return {
        "hours": int(row[0] or 0),
        "min_timestamp": row[1],
        "max_timestamp": row[2],
        "archive_hours": int(row[3] or 0),
    }
