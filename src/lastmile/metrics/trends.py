"""Trends: availability, utilization, and reliability over a trailing window."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..constants import TIMESTAMP_FORMAT
from ..db import queries
from ..settings import get_settings
from .base import BaseMetric

DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class TrendsMetrics(BaseMetric):
    """Historical timeseries behind the Trends view."""

    def get_availability_timeseries(
        self, hours: int | None = 24, region: str | None = None
    ) -> pd.DataFrame:
        """
        Hourly availability, split into the parts that make up the fleet.

        Docked bikes are reported as ``classic_available`` + ``ebikes_available``
        (GBFS counts e-bikes inside ``num_bikes_available``), and free-floating
        bikes are added as their own series so the three stack into the total
        rideable fleet without double counting. Free-floating bikes count as San
        Francisco inventory.
        """
        since = self._since_from_hours(hours)
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

    def get_bike_utilization(
        self,
        hours: int | None = 24 * 28,
        region: str | None = None,
        timeseries: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """
        Estimated bikes in use, by hour of day and by weekday.

        GBFS lists only parked, rentable bikes, so anything being ridden,
        serviced, or carried on a rebalancing van is missing from the count.
        Overnight almost the whole fleet is home, so each day's busiest hour
        in the configured overnight window stands in for its fleet size;
        subtracting the parked count from it estimates how many bikes are away
        at that moment.

        The fleet is re-estimated per day rather than once for the range. Fleet
        size drifts by hundreds of bikes over months, and a single figure makes
        later days read as busy and earlier ones as negative.

        This measures bikes away *at once*, not trips: a ten-minute ride and a
        two-hour one look the same in an hourly snapshot.
        """
        ts = (
            self.get_availability_timeseries(hours=hours, region=region)
            if timeseries is None
            else timeseries
        )
        empty = pd.DataFrame(
            columns=["hour", "bikes_in_use", "avg_parked", "samples"]
        )
        if ts.empty:
            return {
                "baseline": None,
                "baseline_hour": None,
                "by_hour": empty,
                "by_day": empty,
            }

        df = ts.copy()
        df["datetime"] = pd.to_datetime(df["timestamp"], format=TIMESTAMP_FORMAT)
        df["hour"] = df["datetime"].dt.hour
        df["date"] = df["datetime"].dt.normalize()
        df["day_of_week"] = df["datetime"].dt.day_name()

        night = df[df["hour"].isin(get_settings().fleet_baseline_hours)]
        if night.empty:
            # Range misses the overnight window; the calmest hour on record is
            # the closest available stand-in.
            per_date = pd.Series(dtype=float)
            baseline = float(df["total_bikes"].max())
            baseline_hour = None
        else:
            peak = night.loc[night.groupby("date")["total_bikes"].idxmax()]
            per_date = peak.set_index("date")["total_bikes"]
            baseline = float(per_date.median())
            baseline_hour = int(peak["hour"].mode().iloc[0])

        # Days with no overnight snapshot fall back to the typical fleet size.
        fleet = df["date"].map(per_date).fillna(baseline)
        df["bikes_in_use"] = fleet - df["total_bikes"]

        by_hour = (
            df.groupby("hour", as_index=False)
            .agg(
                bikes_in_use=("bikes_in_use", "mean"),
                avg_parked=("total_bikes", "mean"),
                samples=("timestamp", "count"),
            )
            .sort_values("hour")
        )
        by_day = df.groupby("day_of_week", as_index=False).agg(
            bikes_in_use=("bikes_in_use", "mean"),
            avg_parked=("total_bikes", "mean"),
            samples=("timestamp", "count"),
        )
        by_day["day_of_week"] = pd.Categorical(
            by_day["day_of_week"], categories=DAY_ORDER, ordered=True
        )
        by_day = by_day.sort_values("day_of_week")

        return {
            "baseline": baseline,
            "baseline_hour": baseline_hour,
            "by_hour": by_hour,
            "by_day": by_day,
        }

    def get_problematic_by_hour(
        self,
        hours: int | None = 24 * 28,
        region: str | None = None,
    ) -> pd.DataFrame:
        """
        Share of stations flagged as problematic at each clock hour.

        Uses the Live Ops rule: empty or full in any of the trailing daytime
        ops hours. Night hours have an empty lookback, so the rate is zero
        overnight by construction.
        """
        since = self._since_from_hours(hours)
        ts = queries.get_problematic_timeseries(
            self.conn, since=since, region=region
        )
        if ts.empty:
            return pd.DataFrame(columns=["hour", "pct_empty", "pct_full", "samples"])

        df = ts.copy()
        df["hour"] = df["timestamp"].str.slice(11, 13).astype(int)
        total = df["station_count"].replace(0, pd.NA)
        df["pct_empty"] = df["empty_stations"] / total * 100.0
        df["pct_full"] = df["full_stations"] / total * 100.0
        return (
            df.groupby("hour", as_index=False)
            .agg(
                pct_empty=("pct_empty", "mean"),
                pct_full=("pct_full", "mean"),
                samples=("timestamp", "count"),
            )
            .sort_values("hour")
        )

    def get_station_reliability(
        self,
        hours: int | None = 24 * 28,
        region: str | None = None,
        min_hours: int = 24,
    ) -> pd.DataFrame:
        """
        Per-station share of hours spent empty or full over the window.

        Separating the two tells an operator which fix a station needs: a
        chronically empty one wants deliveries, a chronically full one wants
        collections.
        """
        since = self._since_from_hours(hours)
        return queries.get_station_reliability(
            self.conn, since=since, region=region, min_hours=min_hours
        )
