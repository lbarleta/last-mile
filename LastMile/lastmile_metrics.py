"""Metrics derived from stored LastMile snapshots."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

import pandas as pd

from .config import DEFAULT_DB_PATH, DEFAULT_TIMEZONE, TIMESTAMP_FORMAT
from . import lastmile_queries as queries


class LastMileMetrics:
    """Calculate live-ops and historical metrics from the SQLite database."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        timezone: str = DEFAULT_TIMEZONE,
        conn: Optional[sqlite3.Connection] = None,
    ):
        self.db_path = db_path
        self.timezone = timezone
        self._owns_conn = conn is None
        self.conn = conn if conn is not None else queries.connect(db_path)

    def close(self) -> None:
        if self._owns_conn and self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def get_latest_timestamp(self) -> Optional[str]:
        return queries.get_latest_timestamp(self.conn)

    def get_live_ops_metrics(self) -> Dict[str, Any]:
        """KPIs and station tables for the latest hourly snapshot."""
        snapshot = queries.get_latest_station_snapshot(self.conn)
        if snapshot.empty:
            return self._empty_live_ops_metrics(snapshot)

        current = self._snapshot_kpis(snapshot)
        prior_ts = queries.previous_hour_timestamp(current["timestamp"])
        prior_snapshot = queries.get_station_snapshot_at(self.conn, prior_ts)
        prior = (
            self._snapshot_kpis(prior_snapshot)
            if not prior_snapshot.empty
            else None
        )

        free_bikes = queries.get_free_bike_counts(self.conn, current["timestamp"])
        deltas = self._kpi_deltas(current, prior)

        return {
            **current,
            "stations": snapshot,
            "prior_timestamp": prior["timestamp"] if prior else None,
            "free_bikes_total": free_bikes["total"],
            "free_bikes_disabled": free_bikes["disabled"],
            "free_bikes_reserved": free_bikes["reserved"],
            "deltas": deltas,
        }

    def _empty_live_ops_metrics(self, snapshot: pd.DataFrame) -> Dict[str, Any]:
        return {
            "timestamp": None,
            "prior_timestamp": None,
            "total_stations": 0,
            "full_stations": 0,
            "empty_stations": 0,
            "pct_full": 0.0,
            "pct_empty": 0.0,
            "pct_dock_availability": 0.0,
            "docks_available": 0,
            "docks_disabled": 0,
            "total_bikes": 0,
            "ebikes_available": 0,
            "classic_available": 0,
            "ebike_classic_ratio": None,
            "pct_ebike_availability": 0.0,
            "pct_classic_availability": 0.0,
            "bikes_available": 0,
            "bikes_disabled": 0,
            "free_bikes_total": 0,
            "free_bikes_disabled": 0,
            "free_bikes_reserved": 0,
            "stations": snapshot,
            "deltas": {},
        }

    def _snapshot_kpis(self, snapshot: pd.DataFrame) -> Dict[str, Any]:
        empty_mask = snapshot["num_bikes_available"] == 0
        full_mask = snapshot["num_docks_available"] == 0
        total_stations = int(len(snapshot))
        bikes = int(snapshot["num_bikes_available"].sum())
        ebikes = int(snapshot["num_ebikes_available"].sum())
        docks = int(snapshot["num_docks_available"].sum())
        docks_disabled = int(snapshot["num_docks_disabled"].sum())
        bikes_disabled = int(snapshot["num_bikes_disabled"].sum())
        empty_stations = int(empty_mask.sum())
        full_stations = int(full_mask.sum())
        capacity_slots = bikes + docks
        classic = max(bikes - ebikes, 0)
        ratio = (ebikes / classic) if classic > 0 else None

        return {
            "timestamp": snapshot["timestamp"].iloc[0],
            "total_stations": total_stations,
            "full_stations": full_stations,
            "empty_stations": empty_stations,
            "pct_full": (full_stations / total_stations * 100.0) if total_stations else 0.0,
            "pct_empty": (empty_stations / total_stations * 100.0) if total_stations else 0.0,
            "pct_dock_availability": (
                docks / capacity_slots * 100.0 if capacity_slots else 0.0
            ),
            "docks_available": docks,
            "docks_disabled": docks_disabled,
            "total_bikes": bikes,
            "ebikes_available": ebikes,
            "classic_available": classic,
            "ebike_classic_ratio": ratio,
            "pct_ebike_availability": (
                ebikes / capacity_slots * 100.0 if capacity_slots else 0.0
            ),
            "pct_classic_availability": (
                classic / capacity_slots * 100.0 if capacity_slots else 0.0
            ),
            "bikes_available": bikes,
            "bikes_disabled": bikes_disabled,
        }

    def _kpi_deltas(
        self, current: Dict[str, Any], prior: Optional[Dict[str, Any]]
    ) -> Dict[str, Optional[float]]:
        keys = [
            "total_stations",
            "pct_full",
            "pct_empty",
            "pct_dock_availability",
            "docks_available",
            "full_stations",
            "empty_stations",
            "total_bikes",
            "ebike_classic_ratio",
            "pct_ebike_availability",
            "pct_classic_availability",
            "ebikes_available",
            "classic_available",
        ]
        if prior is None:
            return {key: None for key in keys}

        deltas: Dict[str, Optional[float]] = {}
        for key in keys:
            cur = current.get(key)
            old = prior.get(key)
            if cur is None or old is None:
                deltas[key] = None
            else:
                deltas[key] = float(cur) - float(old)
        return deltas

    def get_top_empty_stations(self, n: int = 10) -> pd.DataFrame:
        snapshot = queries.get_latest_station_snapshot(self.conn)
        if snapshot.empty:
            return snapshot
        cols = [
            "name",
            "region",
            "num_bikes_available",
            "num_docks_available",
            "num_ebikes_available",
            "capacity",
        ]
        empty = snapshot[snapshot["num_bikes_available"] == 0].copy()
        return empty.sort_values("num_docks_available", ascending=False).head(n)[cols]

    def get_top_full_stations(self, n: int = 10) -> pd.DataFrame:
        snapshot = queries.get_latest_station_snapshot(self.conn)
        if snapshot.empty:
            return snapshot
        cols = [
            "name",
            "region",
            "num_bikes_available",
            "num_docks_available",
            "num_ebikes_available",
            "capacity",
        ]
        full = snapshot[snapshot["num_docks_available"] == 0].copy()
        return full.sort_values("num_bikes_available", ascending=False).head(n)[cols]

    def get_availability_timeseries(self, hours: Optional[int] = 24) -> pd.DataFrame:
        latest = self.get_latest_timestamp()
        since = queries.cutoff_timestamp(hours, self.timezone, latest) if latest else None
        return queries.get_availability_timeseries(self.conn, since=since)

    def get_hourly_patterns(self, hours: Optional[int] = 24 * 7) -> pd.DataFrame:
        """Average system availability by clock hour (0-23)."""
        ts = self.get_availability_timeseries(hours=hours)
        if ts.empty:
            return ts
        df = ts.copy()
        df["hour"] = df["timestamp"].str.slice(11, 13).astype(int)
        grouped = (
            df.groupby("hour", as_index=False)
            .agg(
                avg_bikes=("bikes_available", "mean"),
                avg_ebikes=("ebikes_available", "mean"),
                avg_docks=("docks_available", "mean"),
                avg_empty=("empty_stations", "mean"),
                samples=("timestamp", "count"),
            )
            .sort_values("hour")
        )
        return grouped

    def get_daily_patterns(self, hours: Optional[int] = 24 * 28) -> pd.DataFrame:
        """Average system availability by day of week."""
        ts = self.get_availability_timeseries(hours=hours)
        if ts.empty:
            return ts
        df = ts.copy()
        df["datetime"] = pd.to_datetime(df["timestamp"], format=TIMESTAMP_FORMAT)
        df["day_of_week"] = df["datetime"].dt.day_name()
        day_order = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        grouped = (
            df.groupby("day_of_week", as_index=False)
            .agg(
                avg_bikes=("bikes_available", "mean"),
                avg_ebikes=("ebikes_available", "mean"),
                avg_docks=("docks_available", "mean"),
                avg_empty=("empty_stations", "mean"),
                samples=("timestamp", "count"),
            )
        )
        grouped["day_of_week"] = pd.Categorical(
            grouped["day_of_week"], categories=day_order, ordered=True
        )
        return grouped.sort_values("day_of_week")

    def get_utilization_distribution(self) -> pd.DataFrame:
        """Latest-snapshot station utilization rates."""
        return queries.get_utilization_snapshot(self.conn)

    # Backwards-compatible alias used by quick_start / older callers
    def get_system_metrics(self, timestamp: Optional[str] = None) -> Dict[str, Any]:
        metrics = self.get_live_ops_metrics()
        stations = metrics.pop("stations")
        return {
            "total_stations": metrics["total_stations"],
            "bikes_available": metrics["bikes_available"],
            "ebikes_available": metrics["ebikes_available"],
            "docks_available": metrics["docks_available"],
            "empty_stations": metrics["empty_stations"],
            "full_stations": metrics["full_stations"],
            "active_stations": int((stations["num_bikes_available"] > 0).sum())
            if not stations.empty
            else 0,
            "timestamp": timestamp or metrics["timestamp"],
        }
