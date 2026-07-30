"""Feature engineering for station-level stockout forecasting.

Snapshots are reshaped into dense ``(hour, station)`` matrices on a complete
hourly grid. Missing snapshots stay as NaN rather than being forward-filled:
gradient boosting handles missing values natively, and pretending a gap was
observed would leak an assumption into the model.

Every feature is split by *when it is known*:

* origin-time state (occupancy and its recent history at time ``t``),
* target-time context (calendar and weather at ``t + h``, both knowable in
  advance), and
* station metadata.

The same-hour-of-day stockout rate deliberately uses a trailing window that
ends at least 24 hours before the target, so it never sees anything the
forecaster would not have had at ``t``. It also serves as the climatology
baseline in backtests.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from .config import (
    FORECAST_CLIMATOLOGY_DAYS,
    FORECAST_HORIZONS,
    FORECAST_LAG_HOURS,
    TIMESTAMP_FORMAT,
)
from . import db as queries
from . import weather as weather_mod

WEATHER_FEATURES = ("temp_c", "precip_mm", "wind_kph", "humidity_pct", "cloud_pct")
CATEGORICAL_FEATURES = ("target_hour", "target_dow", "region_code")

ID_COLUMNS = ("station_id", "origin_timestamp", "target_timestamp")
LABEL_COLUMNS = ("y_empty", "y_full")
BASELINE_COLUMNS = ("base_clim_empty", "base_clim_full")


@dataclass
class StationPanel:
    """Dense hourly grid of station occupancy plus aligned context."""

    timestamps: np.ndarray  # (H,) hourly keys, YYYY-MM-DD-HH:00
    hour_of_day: np.ndarray  # (H,)
    day_of_week: np.ndarray  # (H,)
    month: np.ndarray  # (H,)
    station_ids: np.ndarray  # (S,)
    bikes: np.ndarray  # (H, S) float32, NaN where no snapshot
    docks: np.ndarray  # (H, S)
    ebikes: np.ndarray  # (H, S)
    stations: pd.DataFrame  # static metadata, row-aligned to station_ids
    weather: pd.DataFrame  # (H,) rows, reindexed onto the grid

    @property
    def n_hours(self) -> int:
        return len(self.timestamps)

    @property
    def n_stations(self) -> int:
        return len(self.station_ids)

    def row_of(self, timestamp: str) -> Optional[int]:
        matches = np.nonzero(self.timestamps == timestamp)[0]
        return int(matches[0]) if len(matches) else None


def load_panel(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
    until: Optional[str] = None,
    extend_hours: int = 0,
) -> StationPanel:
    """
    Read snapshots into a dense hourly grid, deduplicating station-hours.

    ``extend_hours`` appends future hours with no occupancy data but valid
    calendar and weather context, which is what scoring beyond the last
    snapshot needs.
    """
    clauses, params = [], []
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until is not None:
        clauses.append("timestamp <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    status = pd.read_sql_query(
        f"""
        SELECT station_id, timestamp,
               num_bikes_available, num_docks_available, num_ebikes_available
        FROM station_status
        {where}
        """,
        conn,
        params=params,
    )
    if status.empty:
        raise ValueError("No station_status rows in the requested window")

    # The collector appends without a uniqueness constraint, so retries and the
    # DST fall-back hour can produce repeated station-hours.
    status = status.drop_duplicates(subset=["station_id", "timestamp"], keep="last")
    status["station_id"] = status["station_id"].astype(str)

    observed = pd.to_datetime(status["timestamp"], format=TIMESTAMP_FORMAT)
    grid_end = observed.max() + pd.Timedelta(hours=max(0, extend_hours))
    grid = pd.date_range(observed.min(), grid_end, freq="h")
    timestamps = np.array(grid.strftime(TIMESTAMP_FORMAT))

    stations = _load_station_metadata(conn)
    station_ids = stations["station_id"].to_numpy()

    row_of = pd.Index(timestamps)
    col_of = pd.Index(station_ids)
    rows = row_of.get_indexer(status["timestamp"].to_numpy())
    cols = col_of.get_indexer(status["station_id"].to_numpy())
    keep = (rows >= 0) & (cols >= 0)
    rows, cols = rows[keep], cols[keep]

    shape = (len(timestamps), len(station_ids))
    matrices = {}
    for name, column in (
        ("bikes", "num_bikes_available"),
        ("docks", "num_docks_available"),
        ("ebikes", "num_ebikes_available"),
    ):
        mat = np.full(shape, np.nan, dtype=np.float32)
        mat[rows, cols] = pd.to_numeric(
            status[column][keep], errors="coerce"
        ).to_numpy(dtype=np.float32)
        matrices[name] = mat

    weather = weather_mod.load_weather(conn)
    weather = (
        weather.set_index("timestamp")
        .reindex(timestamps)
        .reset_index(names="timestamp")
    )

    return StationPanel(
        timestamps=timestamps,
        hour_of_day=grid.hour.to_numpy(dtype=np.int16),
        day_of_week=grid.dayofweek.to_numpy(dtype=np.int16),
        month=grid.month.to_numpy(dtype=np.int16),
        station_ids=station_ids,
        bikes=matrices["bikes"],
        docks=matrices["docks"],
        ebikes=matrices["ebikes"],
        stations=stations,
        weather=weather,
    )


def _load_station_metadata(conn: sqlite3.Connection) -> pd.DataFrame:
    name_col = queries._station_name_expr(conn)
    stations = pd.read_sql_query(
        f"""
        SELECT s.station_id,
               {name_col} AS name,
               COALESCE(s.region, 'Unknown') AS region,
               s.capacity, s.lat, s.lon
        FROM stations s
        """,
        conn,
    )
    stations["station_id"] = stations["station_id"].astype(str)
    stations = stations.drop_duplicates(subset=["station_id"]).sort_values("station_id")
    stations["region_code"] = (
        stations["region"].astype("category").cat.codes.astype(np.int16)
    )
    for col in ("capacity", "lat", "lon"):
        stations[col] = pd.to_numeric(stations[col], errors="coerce")
    return stations.reset_index(drop=True)


# --- rolling helpers ------------------------------------------------------


def _lag(mat: np.ndarray, k: int) -> np.ndarray:
    """Shift a (H, S) matrix forward in time by k hours."""
    out = np.full_like(mat, np.nan)
    if k < mat.shape[0]:
        out[k:] = mat[:-k] if k else mat
    return out


def _trailing_mean(
    mat: np.ndarray, window: int, *, inclusive: bool = True
) -> np.ndarray:
    """Mean of the previous `window` rows, ignoring NaN."""
    n_rows, n_cols = mat.shape
    valid = (~np.isnan(mat)).astype(np.float32)
    filled = np.nan_to_num(mat, nan=0.0).astype(np.float32)
    zeros = np.zeros((1, n_cols), dtype=np.float32)
    csum = np.vstack([zeros, np.cumsum(filled, axis=0)])
    ccnt = np.vstack([zeros, np.cumsum(valid, axis=0)])

    end = np.arange(1, n_rows + 1) if inclusive else np.arange(n_rows)
    start = np.maximum(end - window, 0)
    total = csum[end] - csum[start]
    count = ccnt[end] - ccnt[start]
    return np.divide(
        total, count, out=np.full_like(total, np.nan), where=count > 0
    )


def _same_hour_trailing_rate(
    mat: np.ndarray, hour_of_day: np.ndarray, window_days: int
) -> np.ndarray:
    """
    Rate over the last `window_days` occurrences of the same hour of day.

    Strictly excludes the current row, so a value read at t+h only reflects
    observations from t+h-24 and earlier — before the forecast origin.
    """
    out = np.full_like(mat, np.nan)
    for hour in range(24):
        idx = np.nonzero(hour_of_day == hour)[0]
        if idx.size == 0:
            continue
        out[idx] = _trailing_mean(mat[idx], window_days, inclusive=False)
    return out


# --- feature assembly -----------------------------------------------------


def _state_features(panel: StationPanel) -> dict[str, np.ndarray]:
    """Everything knowable about a station at the forecast origin."""
    bikes, docks = panel.bikes, panel.docks
    slots = bikes + docks
    with np.errstate(invalid="ignore", divide="ignore"):
        fill = np.where(slots > 0, bikes / slots, np.nan).astype(np.float32)

    is_empty = (bikes == 0).astype(np.float32)
    is_empty[np.isnan(bikes)] = np.nan
    is_full = (docks == 0).astype(np.float32)
    is_full[np.isnan(docks)] = np.nan

    features: dict[str, np.ndarray] = {
        "bikes": bikes,
        "docks": docks,
        "ebikes": panel.ebikes,
        "slots": slots,
        "fill": fill,
        "is_empty": is_empty,
        "is_full": is_full,
    }
    for lag in FORECAST_LAG_HOURS:
        features[f"fill_lag_{lag}"] = _lag(fill, lag)
    features["fill_delta_1h"] = fill - features["fill_lag_1"]
    features["fill_delta_3h"] = fill - features["fill_lag_3"]
    features["fill_mean_3h"] = _trailing_mean(fill, 3)
    features["fill_mean_24h"] = _trailing_mean(fill, 24)
    features["empty_rate_24h"] = _trailing_mean(is_empty, 24)
    features["empty_rate_168h"] = _trailing_mean(is_empty, 168)
    features["full_rate_24h"] = _trailing_mean(is_full, 24)
    return features


def _climatology(panel: StationPanel) -> tuple[np.ndarray, np.ndarray]:
    """Trailing same-hour-of-day empty / full rates per station."""
    is_empty = (panel.bikes == 0).astype(np.float32)
    is_empty[np.isnan(panel.bikes)] = np.nan
    is_full = (panel.docks == 0).astype(np.float32)
    is_full[np.isnan(panel.docks)] = np.nan
    return (
        _same_hour_trailing_rate(
            is_empty, panel.hour_of_day, FORECAST_CLIMATOLOGY_DAYS
        ),
        _same_hour_trailing_rate(
            is_full, panel.hour_of_day, FORECAST_CLIMATOLOGY_DAYS
        ),
    )


def _weather_frame(panel: StationPanel) -> pd.DataFrame:
    weather = panel.weather.copy()
    for col in WEATHER_FEATURES:
        if col not in weather.columns:
            weather[col] = np.nan
        weather[col] = pd.to_numeric(weather[col], errors="coerce").astype("float32")
    weather["precip_3h"] = (
        weather["precip_mm"].rolling(3, min_periods=1).sum().astype("float32")
    )
    return weather[[*WEATHER_FEATURES, "precip_3h"]]


def build_features(
    panel: StationPanel,
    *,
    horizons: Sequence[int] = FORECAST_HORIZONS,
    origin_rows: Optional[np.ndarray] = None,
    with_labels: bool = True,
    max_rows: Optional[int] = None,
    seed: int = 7,
) -> pd.DataFrame:
    """
    Long-form training / scoring frame: one row per origin hour, station, horizon.

    Rows without a usable observation at the origin are dropped. When
    ``with_labels`` is set, rows whose target hour was never observed are
    dropped too, so labels are never imputed.
    """
    state = _state_features(panel)
    clim_empty, clim_full = _climatology(panel)
    weather = _weather_frame(panel)
    static = panel.stations.set_index("station_id").loc[panel.station_ids]

    n_hours = panel.n_hours
    if origin_rows is None:
        origin_rows = np.arange(n_hours)
    origin_rows = np.asarray(origin_rows, dtype=int)

    rng = np.random.default_rng(seed)
    per_horizon = (
        None if max_rows is None else max(1, max_rows // max(1, len(horizons)))
    )

    chunks = []
    for horizon in horizons:
        rows = origin_rows[origin_rows + horizon < n_hours]
        if rows.size == 0:
            continue
        target_rows = rows + horizon

        observed = ~np.isnan(panel.bikes[rows])
        if with_labels:
            observed &= ~np.isnan(panel.bikes[target_rows])
        r_idx, s_idx = np.nonzero(observed)
        if r_idx.size == 0:
            continue

        if per_horizon is not None and r_idx.size > per_horizon:
            pick = rng.choice(r_idx.size, size=per_horizon, replace=False)
            pick.sort()
            r_idx, s_idx = r_idx[pick], s_idx[pick]

        origin_idx = rows[r_idx]
        target_idx = target_rows[r_idx]

        frame = {
            "station_id": panel.station_ids[s_idx],
            "origin_timestamp": panel.timestamps[origin_idx],
            "target_timestamp": panel.timestamps[target_idx],
            "horizon": np.full(r_idx.size, horizon, dtype=np.int16),
        }
        for name, mat in state.items():
            frame[name] = mat[origin_idx, s_idx]

        frame["target_hour"] = panel.hour_of_day[target_idx]
        frame["target_dow"] = panel.day_of_week[target_idx]
        frame["target_is_weekend"] = (
            panel.day_of_week[target_idx] >= 5
        ).astype(np.int8)
        frame["target_month"] = panel.month[target_idx]
        frame["clim_empty"] = clim_empty[target_idx, s_idx]
        frame["clim_full"] = clim_full[target_idx, s_idx]

        for col in weather.columns:
            frame[col] = weather[col].to_numpy()[target_idx]

        frame["capacity"] = static["capacity"].to_numpy()[s_idx]
        frame["lat"] = static["lat"].to_numpy()[s_idx]
        frame["lon"] = static["lon"].to_numpy()[s_idx]
        frame["region_code"] = static["region_code"].to_numpy()[s_idx]

        if with_labels:
            frame["y_empty"] = (panel.bikes[target_idx, s_idx] == 0).astype(np.int8)
            frame["y_full"] = (panel.docks[target_idx, s_idx] == 0).astype(np.int8)

        chunks.append(pd.DataFrame(frame))

    if not chunks:
        return pd.DataFrame()

    out = pd.concat(chunks, ignore_index=True)
    out["base_clim_empty"] = out["clim_empty"]
    out["base_clim_full"] = out["clim_full"]
    return out


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Model input columns: everything that is not an id, label, or baseline."""
    excluded = {*ID_COLUMNS, *LABEL_COLUMNS, *BASELINE_COLUMNS}
    return [col for col in frame.columns if col not in excluded]
