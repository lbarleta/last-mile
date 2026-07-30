"""Metrics derived from stored LastMile snapshots."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

import pandas as pd

from .config import (
    DEFAULT_DB_PATH,
    DEFAULT_TIMEZONE,
    FORECAST_RISK_THRESHOLD,
    LOW_RANGE_METERS,
    TIMESTAMP_FORMAT,
)
from . import db as queries
from . import coverage as coverage_mod
from . import forecast as forecast_mod


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

    def list_snapshot_dates(self) -> list[str]:
        return queries.list_snapshot_dates(self.conn)

    def list_snapshot_hours_for_date(self, date_str: str) -> list[str]:
        return queries.list_snapshot_hours_for_date(self.conn, date_str)

    def get_live_ops_metrics(self, timestamp: Optional[str] = None) -> Dict[str, Any]:
        """KPIs and station tables for a hourly snapshot (latest if omitted)."""
        if timestamp is None:
            snapshot = queries.get_latest_station_snapshot(self.conn)
        else:
            snapshot = queries.get_station_snapshot_at(self.conn, timestamp)
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

        free_bikes = queries.get_free_bike_counts(
            self.conn, current["timestamp"], low_range_meters=LOW_RANGE_METERS
        )
        prior_free = (
            queries.get_free_bike_counts(
                self.conn, prior["timestamp"], low_range_meters=LOW_RANGE_METERS
            )
            if prior
            else None
        )
        station_bikes = current["total_bikes"]
        free_total = free_bikes["total"]
        all_bikes = station_bikes + free_total
        disabled_bikes = current["bikes_disabled"] + free_bikes["disabled"]
        low_range = free_bikes["low_range"]
        current["available_bikes"] = all_bikes
        current["free_bikes_total"] = free_total
        current["free_bikes_disabled"] = free_bikes["disabled"]
        current["free_bikes_reserved"] = free_bikes["reserved"]
        current["low_range_bikes"] = low_range
        classic = current["classic_available"]
        ebikes = current["ebikes_available"]
        current["pct_docked_classic"] = (
            classic / all_bikes * 100.0 if all_bikes else 0.0
        )
        current["pct_docked_ebike"] = (
            ebikes / all_bikes * 100.0 if all_bikes else 0.0
        )
        current["pct_free_range"] = (
            free_total / all_bikes * 100.0 if all_bikes else 0.0
        )
        current["pct_low_range"] = (
            low_range / free_total * 100.0 if free_total else 0.0
        )
        current["disabled_bikes_total"] = disabled_bikes
        current["pct_disabled_bikes"] = (
            disabled_bikes / all_bikes * 100.0 if all_bikes else 0.0
        )

        free_bike_locs = queries.get_free_bike_snapshot(
            self.conn, current["timestamp"]
        )
        current["avg_dist_to_station_m"] = queries.avg_distance_to_nearest_station_m(
            snapshot, free_bike_locs
        )

        coverage = coverage_mod.compute_sf_coverage(snapshot, free_bike_locs)
        current["pct_sf_coverage"] = coverage["pct_coverage"]
        current["coverage_geojson"] = coverage["coverage_geojson"]
        current["coverage_n_sources"] = coverage["n_sources"]

        deltas = self._kpi_deltas(current, prior)
        if prior is not None and prior_free is not None:
            prior_all = prior["total_bikes"] + prior_free["total"]
            prior_disabled = prior["bikes_disabled"] + prior_free["disabled"]
            prior_classic = prior["classic_available"]
            prior_ebikes = prior["ebikes_available"]
            prior_pct_classic = (
                prior_classic / prior_all * 100.0 if prior_all else 0.0
            )
            prior_pct_ebike = (
                prior_ebikes / prior_all * 100.0 if prior_all else 0.0
            )
            prior_pct_free = (
                prior_free["total"] / prior_all * 100.0 if prior_all else 0.0
            )
            prior_pct_disabled = (
                prior_disabled / prior_all * 100.0 if prior_all else 0.0
            )
            prior_pct_low = (
                prior_free["low_range"] / prior_free["total"] * 100.0
                if prior_free["total"]
                else 0.0
            )
            deltas["available_bikes"] = float(all_bikes - prior_all)
            deltas["pct_docked_classic"] = (
                current["pct_docked_classic"] - prior_pct_classic
            )
            deltas["pct_docked_ebike"] = (
                current["pct_docked_ebike"] - prior_pct_ebike
            )
            deltas["pct_free_range"] = current["pct_free_range"] - prior_pct_free
            deltas["free_bikes_total"] = float(
                free_total - prior_free["total"]
            )
            deltas["disabled_bikes_total"] = float(
                disabled_bikes - prior_disabled
            )
            deltas["pct_disabled_bikes"] = (
                current["pct_disabled_bikes"] - prior_pct_disabled
            )
            deltas["low_range_bikes"] = float(
                low_range - prior_free["low_range"]
            )
            deltas["pct_low_range"] = current["pct_low_range"] - prior_pct_low

            prior_bike_locs = queries.get_free_bike_snapshot(
                self.conn, prior["timestamp"]
            )
            prior_avg = queries.avg_distance_to_nearest_station_m(
                prior_snapshot, prior_bike_locs
            )
            if (
                current["avg_dist_to_station_m"] is not None
                and prior_avg is not None
            ):
                deltas["avg_dist_to_station_m"] = (
                    current["avg_dist_to_station_m"] - prior_avg
                )
            else:
                deltas["avg_dist_to_station_m"] = None

            prior_cov = coverage_mod.compute_sf_coverage(
                prior_snapshot, prior_bike_locs
            )
            deltas["pct_sf_coverage"] = (
                current["pct_sf_coverage"] - prior_cov["pct_coverage"]
            )
        else:
            deltas["available_bikes"] = None
            deltas["pct_docked_classic"] = None
            deltas["pct_docked_ebike"] = None
            deltas["pct_free_range"] = None
            deltas["free_bikes_total"] = None
            deltas["disabled_bikes_total"] = None
            deltas["pct_disabled_bikes"] = None
            deltas["low_range_bikes"] = None
            deltas["pct_low_range"] = None
            deltas["avg_dist_to_station_m"] = None
            deltas["pct_sf_coverage"] = None

        return {
            **current,
            "stations": snapshot,
            "prior_timestamp": prior["timestamp"] if prior else None,
            "deltas": deltas,
        }

    def _empty_live_ops_metrics(self, snapshot: pd.DataFrame) -> Dict[str, Any]:
        return {
            "timestamp": None,
            "prior_timestamp": None,
            "total_stations": 0,
            "full_stations": 0,
            "empty_stations": 0,
            "healthy_stations": 0,
            "low_stations": 0,
            "pct_full": 0.0,
            "pct_empty": 0.0,
            "pct_healthy": 0.0,
            "pct_low": 0.0,
            "pct_dock_availability": 0.0,
            "pct_docks_disabled": 0.0,
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
            "available_bikes": 0,
            "free_bikes_total": 0,
            "free_bikes_disabled": 0,
            "free_bikes_reserved": 0,
            "low_range_bikes": 0,
            "pct_docked_classic": 0.0,
            "pct_docked_ebike": 0.0,
            "pct_free_range": 0.0,
            "pct_low_range": 0.0,
            "disabled_bikes_total": 0,
            "pct_disabled_bikes": 0.0,
            "avg_dist_to_station_m": None,
            "pct_sf_coverage": 0.0,
            "coverage_geojson": None,
            "coverage_n_sources": 0,
            "stations": snapshot,
            "deltas": {},
        }

    def _snapshot_kpis(self, snapshot: pd.DataFrame) -> Dict[str, Any]:
        def _bucket(row: pd.Series) -> str:
            if row["num_bikes_available"] == 0:
                return "empty"
            if row["num_docks_available"] == 0:
                return "full"
            capacity = row["num_bikes_available"] + row["num_docks_available"]
            if capacity > 0 and row["num_bikes_available"] / capacity < 0.2:
                return "low"
            return "healthy"

        status = snapshot.apply(_bucket, axis=1)
        empty_stations = int((status == "empty").sum())
        full_stations = int((status == "full").sum())
        healthy_stations = int((status == "healthy").sum())
        low_stations = int((status == "low").sum())
        total_stations = int(len(snapshot))
        bikes = int(snapshot["num_bikes_available"].sum())
        ebikes = int(snapshot["num_ebikes_available"].sum())
        docks = int(snapshot["num_docks_available"].sum())
        docks_disabled = int(snapshot["num_docks_disabled"].sum())
        bikes_disabled = int(snapshot["num_bikes_disabled"].sum())
        capacity_slots = bikes + docks
        dock_inventory = docks + docks_disabled
        classic = max(bikes - ebikes, 0)
        ratio = (ebikes / classic) if classic > 0 else None

        return {
            "timestamp": snapshot["timestamp"].iloc[0],
            "total_stations": total_stations,
            "full_stations": full_stations,
            "empty_stations": empty_stations,
            "healthy_stations": healthy_stations,
            "low_stations": low_stations,
            "pct_full": (full_stations / total_stations * 100.0) if total_stations else 0.0,
            "pct_empty": (empty_stations / total_stations * 100.0) if total_stations else 0.0,
            "pct_healthy": (
                healthy_stations / total_stations * 100.0 if total_stations else 0.0
            ),
            "pct_low": (low_stations / total_stations * 100.0) if total_stations else 0.0,
            "pct_dock_availability": (
                docks / capacity_slots * 100.0 if capacity_slots else 0.0
            ),
            "pct_docks_disabled": (
                docks_disabled / dock_inventory * 100.0 if dock_inventory else 0.0
            ),
            "docks_available": docks,
            "docks_disabled": docks_disabled,
            "total_bikes": bikes,
            "ebikes_available": ebikes,
            "classic_available": classic,
            "ebike_classic_ratio": ratio,
            "pct_ebike_availability": (
                ebikes / bikes * 100.0 if bikes else 0.0
            ),
            "pct_classic_availability": (
                classic / bikes * 100.0 if bikes else 0.0
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
            "pct_healthy",
            "pct_low",
            "pct_dock_availability",
            "pct_docks_disabled",
            "docks_available",
            "docks_disabled",
            "full_stations",
            "empty_stations",
            "healthy_stations",
            "low_stations",
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

    def get_free_bikes(self, timestamp: Optional[str] = None) -> pd.DataFrame:
        """Free-range bike locations for map rendering."""
        ts = timestamp or self.get_latest_timestamp()
        if ts is None:
            return pd.DataFrame()
        return queries.get_free_bike_snapshot(self.conn, ts)

    def get_problematic_stations(
        self, timestamp: Optional[str] = None
    ) -> pd.DataFrame:
        """Stations empty/full in the last daytime ops hours before ``timestamp``."""
        ts = timestamp or self.get_latest_timestamp()
        if ts is None:
            return pd.DataFrame()
        return queries.get_problematic_stations(self.conn, ts)

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

    def get_station_status_by_region(
        self, timestamp: Optional[str] = None
    ) -> pd.DataFrame:
        """Station availability mix (%) by region for a snapshot (latest if omitted)."""
        if timestamp is None:
            snapshot = queries.get_latest_station_snapshot(self.conn)
        else:
            snapshot = queries.get_station_snapshot_at(self.conn, timestamp)
        statuses = ["empty", "low", "healthy", "full"]
        if snapshot.empty:
            cols = ["region", "total", *statuses, *[f"pct_{s}" for s in statuses]]
            return pd.DataFrame(columns=cols)

        def _bucket(row: pd.Series) -> str:
            if row["num_bikes_available"] == 0:
                return "empty"
            if row["num_docks_available"] == 0:
                return "full"
            capacity = row["num_bikes_available"] + row["num_docks_available"]
            if capacity > 0 and row["num_bikes_available"] / capacity < 0.2:
                return "low"
            return "healthy"

        df = snapshot.copy()
        df["region"] = df["region"].fillna("Unknown")
        df["status"] = df.apply(_bucket, axis=1)

        grouped = (
            df.groupby(["region", "status"], as_index=False)
            .size()
            .rename(columns={"size": "count"})
        )
        totals = (
            df.groupby("region", as_index=False)
            .size()
            .rename(columns={"size": "total"})
        )
        pivot = (
            grouped.pivot(index="region", columns="status", values="count")
            .reindex(columns=statuses, fill_value=0)
            .fillna(0)
            .astype(int)
            .reset_index()
        )
        result = totals.merge(pivot, on="region", how="left")
        for status in statuses:
            if status not in result.columns:
                result[status] = 0
            result[f"pct_{status}"] = result[status] / result["total"] * 100.0
        return result.sort_values("total", ascending=False)

    def get_empty_full_by_region(self) -> pd.DataFrame:
        """Backward-compatible alias for station status mix by region."""
        return self.get_station_status_by_region()

    def list_regions(self) -> list[str]:
        """Station regions available for filtering."""
        return queries.list_regions(self.conn)

    def get_availability_timeseries(
        self, hours: Optional[int] = 24, region: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Hourly availability, split into the parts that make up the fleet.

        Docked bikes are reported as ``classic_available`` + ``ebikes_available``
        (GBFS counts e-bikes inside ``num_bikes_available``), and free-floating
        bikes are added as their own series so the three stack into the total
        rideable fleet without double counting.
        """
        latest = self.get_latest_timestamp()
        since = queries.cutoff_timestamp(hours, self.timezone, latest) if latest else None
        docked = queries.get_availability_timeseries(
            self.conn, since=since, region=region
        )
        if docked.empty:
            return docked

        free = queries.get_free_bike_timeseries(
            self.conn, since=since, region=region
        )
        merged = docked.merge(free, on="timestamp", how="left")
        merged["free_floating"] = merged["free_floating"].fillna(0).astype(int)
        merged["total_bikes"] = (
            merged["classic_available"]
            + merged["ebikes_available"]
            + merged["free_floating"]
        )
        return merged

    def get_hourly_patterns(
        self,
        hours: Optional[int] = 24 * 7,
        region: Optional[str] = None,
        timeseries: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Average system availability by clock hour (0-23)."""
        ts = (
            self.get_availability_timeseries(hours=hours, region=region)
            if timeseries is None
            else timeseries
        )
        if ts.empty:
            return ts
        df = ts.copy()
        df["hour"] = df["timestamp"].str.slice(11, 13).astype(int)
        grouped = (
            df.groupby("hour", as_index=False)
            .agg(
                avg_bikes=("total_bikes", "mean"),
                avg_ebikes=("ebikes_available", "mean"),
                avg_docks=("docks_available", "mean"),
                avg_empty=("empty_stations", "mean"),
                samples=("timestamp", "count"),
            )
            .sort_values("hour")
        )
        return grouped

    def get_daily_patterns(
        self,
        hours: Optional[int] = 24 * 28,
        region: Optional[str] = None,
        timeseries: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Average system availability by day of week."""
        ts = (
            self.get_availability_timeseries(hours=hours, region=region)
            if timeseries is None
            else timeseries
        )
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
                avg_bikes=("total_bikes", "mean"),
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

    def get_utilization_distribution(
        self, region: Optional[str] = None
    ) -> pd.DataFrame:
        """Latest-snapshot station utilization rates."""
        return queries.get_utilization_snapshot(self.conn, region=region)

    # --- stockout forecast ------------------------------------------------

    def get_forecast(self, origin_timestamp: Optional[str] = None) -> pd.DataFrame:
        """Stored per-station stockout probabilities for one forecast origin."""
        return forecast_mod.load_predictions(self.conn, origin_timestamp)

    def get_forecast_origin(self) -> Optional[str]:
        return forecast_mod.latest_forecast_origin(self.conn)

    def get_forecast_outlook(
        self,
        forecast: Optional[pd.DataFrame] = None,
        threshold: float = FORECAST_RISK_THRESHOLD,
    ) -> pd.DataFrame:
        """Count of stations above the risk threshold at each forecast hour."""
        df = self.get_forecast() if forecast is None else forecast
        if df.empty:
            return pd.DataFrame(
                columns=["horizon", "target_timestamp", "at_risk_empty", "at_risk_full"]
            )
        return (
            df.assign(
                at_risk_empty=(df["p_empty"] >= threshold).astype(int),
                at_risk_full=(df["p_full"] >= threshold).astype(int),
            )
            .groupby(["horizon", "target_timestamp"], as_index=False)
            .agg(
                at_risk_empty=("at_risk_empty", "sum"),
                at_risk_full=("at_risk_full", "sum"),
                expected_empty=("p_empty", "sum"),
                expected_full=("p_full", "sum"),
                stations=("station_id", "count"),
            )
            .sort_values("horizon")
        )

    def get_forecast_watchlist(
        self,
        forecast: Optional[pd.DataFrame] = None,
        threshold: float = FORECAST_RISK_THRESHOLD,
    ) -> pd.DataFrame:
        """
        Stations predicted to run empty or full, ranked by peak risk.

        ``lead_hours`` is how far ahead the first threshold crossing is — the
        dispatch window an operator actually has.
        """
        df = self.get_forecast() if forecast is None else forecast
        columns = [
            "station_id",
            "name",
            "region",
            "bikes_now",
            "docks_now",
            "issue",
            "peak_risk",
            "lead_hours",
            "first_hour",
        ]
        if df.empty:
            return pd.DataFrame(columns=columns)

        flagged = df[(df["p_empty"] >= threshold) | (df["p_full"] >= threshold)]
        if flagged.empty:
            return pd.DataFrame(columns=columns)

        rows = []
        for station_id, group in flagged.groupby("station_id", sort=False):
            group = group.sort_values("horizon")
            peak_empty = float(group["p_empty"].max())
            peak_full = float(group["p_full"].max())
            issue = "Empty" if peak_empty >= peak_full else "Full"
            risk_col = "p_empty" if issue == "Empty" else "p_full"
            crossing = group[group[risk_col] >= threshold]
            if crossing.empty:
                crossing = group
            first = crossing.iloc[0]
            head = group.iloc[0]
            rows.append(
                {
                    "station_id": station_id,
                    "name": head.get("name") or station_id,
                    "region": head.get("region") or "Unknown",
                    "bikes_now": head.get("bikes_now"),
                    "docks_now": head.get("docks_now"),
                    "issue": issue,
                    "peak_risk": max(peak_empty, peak_full),
                    "lead_hours": int(first["horizon"]),
                    "first_hour": first["target_timestamp"],
                }
            )

        out = pd.DataFrame(rows, columns=columns)
        return out.sort_values(
            ["peak_risk", "lead_hours"], ascending=[False, True]
        ).reset_index(drop=True)

    def get_forecast_evaluation(self) -> pd.DataFrame:
        """Rolling-origin backtest metrics for the model and its baselines."""
        return forecast_mod.load_metrics(self.conn)

    def get_forecast_calibration(self) -> pd.DataFrame:
        """Pooled reliability bins from the most recent backtest."""
        return forecast_mod.load_calibration(self.conn)

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
