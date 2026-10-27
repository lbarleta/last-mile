"""Live Ops: the current snapshot's KPIs, station tables, and coverage."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..constants import TIMESTAMP_FORMAT
from ..db import queries
from ..settings import get_settings
from . import coverage
from .base import BaseMetric


def station_status_bucket(row: pd.Series) -> str:
    """One of empty / full / low / healthy; empty wins when both are zero."""
    if row["num_bikes_available"] == 0:
        return "empty"
    if row["num_docks_available"] == 0:
        return "full"
    capacity = row["num_bikes_available"] + row["num_docks_available"]
    low_share = get_settings().low_station_bike_share
    if capacity > 0 and row["num_bikes_available"] / capacity < low_share:
        return "low"
    return "healthy"


class LiveOpsMetrics(BaseMetric):
    """KPIs and station tables for a single snapshot hour."""

    def get_live_ops_metrics(self, timestamp: str | None = None) -> dict[str, Any]:
        """KPIs and station tables for an hourly snapshot (latest if omitted)."""
        if timestamp is None:
            snapshot = queries.get_latest_station_snapshot(self.conn)
        else:
            snapshot = queries.get_station_snapshot_at(self.conn, timestamp)
        if snapshot.empty:
            return self._empty_live_ops_metrics(snapshot)

        low_range_meters = get_settings().low_range_meters
        current = self._snapshot_kpis(snapshot)
        prior_ts = queries.previous_hour_timestamp(current["timestamp"])
        prior_snapshot = queries.get_station_snapshot_at(self.conn, prior_ts)
        prior = (
            self._snapshot_kpis(prior_snapshot)
            if not prior_snapshot.empty
            else None
        )

        free_bikes = queries.get_free_bike_counts(
            self.conn, current["timestamp"], low_range_meters=low_range_meters
        )
        prior_free = (
            queries.get_free_bike_counts(
                self.conn, prior["timestamp"], low_range_meters=low_range_meters
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

        cov = coverage.compute_coverage(snapshot, free_bike_locs)
        current["pct_sf_coverage"] = cov["pct_coverage"]
        current["coverage_geojson"] = cov["coverage_geojson"]
        current["coverage_n_sources"] = cov["n_sources"]

        open_docks = current["docks_available"]
        ratio = all_bikes / open_docks * 10.0 if open_docks else None
        typical, samples = self._supply_ratio_baseline(current["timestamp"])
        current["bikes_per_10_docks"] = ratio
        current["bikes_per_10_docks_typical"] = typical
        current["bikes_per_10_docks_samples"] = samples
        current["bikes_per_10_docks_vs_typical"] = (
            ratio - typical if ratio is not None and typical is not None else None
        )

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

            prior_cov = coverage.compute_coverage(prior_snapshot, prior_bike_locs)
            deltas["pct_sf_coverage"] = (
                current["pct_sf_coverage"] - prior_cov["pct_coverage"]
            )
        else:
            for key in (
                "available_bikes",
                "pct_docked_classic",
                "pct_docked_ebike",
                "pct_free_range",
                "free_bikes_total",
                "disabled_bikes_total",
                "pct_disabled_bikes",
                "low_range_bikes",
                "pct_low_range",
                "avg_dist_to_station_m",
                "pct_sf_coverage",
            ):
                deltas[key] = None

        return {
            **current,
            "stations": snapshot,
            "prior_timestamp": prior["timestamp"] if prior else None,
            "deltas": deltas,
        }

    def _supply_ratio_baseline(
        self, timestamp: str, days: int | None = None
    ) -> tuple[float | None, int]:
        """
        Mean bikes per 10 docks at the same hour of day over the trailing window.

        The ratio sits in a narrow band overall but follows a daily cycle, so a
        flat average would read as drift. Holding the hour fixed makes the
        comparison show only departures from the normal rhythm.
        """
        if days is None:
            days = get_settings().supply_baseline_days
        origin = pd.to_datetime(timestamp, format=TIMESTAMP_FORMAT, errors="coerce")
        if pd.isna(origin):
            return None, 0
        since = (origin - pd.Timedelta(days=days)).strftime(TIMESTAMP_FORMAT)
        until = (origin - pd.Timedelta(hours=1)).strftime(TIMESTAMP_FORMAT)
        hour = origin.strftime("%H")

        docked = queries.get_availability_timeseries(
            self.conn, since=since, until=until, hour_of_day=hour
        )
        if docked.empty:
            return None, 0
        free = queries.get_free_bike_timeseries(
            self.conn, since=since, until=until, hour_of_day=hour
        )
        merged = docked.merge(free, on="timestamp", how="left")
        merged["free_floating"] = merged["free_floating"].fillna(0)
        bikes = merged["bikes_available"] + merged["free_floating"]
        open_docks = merged["docks_available"].where(merged["docks_available"] > 0)
        ratio = (bikes / open_docks * 10.0).dropna()
        if ratio.empty:
            return None, 0
        return float(ratio.mean()), int(ratio.size)

    def _empty_live_ops_metrics(self, snapshot: pd.DataFrame) -> dict[str, Any]:
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
            "bikes_per_10_docks": None,
            "bikes_per_10_docks_typical": None,
            "bikes_per_10_docks_samples": 0,
            "bikes_per_10_docks_vs_typical": None,
            "pct_sf_coverage": 0.0,
            "coverage_geojson": None,
            "coverage_n_sources": 0,
            "stations": snapshot,
            "deltas": {},
        }

    def _snapshot_kpis(self, snapshot: pd.DataFrame) -> dict[str, Any]:
        status = snapshot.apply(station_status_bucket, axis=1)
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
        self, current: dict[str, Any], prior: dict[str, Any] | None
    ) -> dict[str, float | None]:
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

        deltas: dict[str, float | None] = {}
        for key in keys:
            cur = current.get(key)
            old = prior.get(key)
            if cur is None or old is None:
                deltas[key] = None
            else:
                deltas[key] = float(cur) - float(old)
        return deltas

    # --- station tables -----------------------------------------------------

    def get_free_bikes(self, timestamp: str | None = None) -> pd.DataFrame:
        """Free-range bike locations for map rendering."""
        ts = timestamp or self.get_latest_timestamp()
        if ts is None:
            return pd.DataFrame()
        return queries.get_free_bike_snapshot(self.conn, ts)

    def get_problematic_stations(
        self, timestamp: str | None = None
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
        self, timestamp: str | None = None
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

        df = snapshot.copy()
        df["region"] = df["region"].fillna("Unknown")
        df["status"] = df.apply(station_status_bucket, axis=1)

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
