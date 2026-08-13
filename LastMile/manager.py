"""Hourly GBFS collection."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .engine import rows_from_frame
from .utils import LastMileUtils, as_int_flag, count_electric

STATION_COLUMNS = [
    "station_id", "ts", "num_bikes_available", "num_docks_available",
    "num_ebikes_available", "num_docks_disabled", "num_bikes_disabled",
    "is_installed", "is_renting", "is_returning", "last_reported",
]
BIKE_COLUMNS = [
    "bike_id", "ts", "lat", "lon", "is_reserved", "is_disabled",
    "vehicle_type_id", "current_range_meters", "last_reported",
]


class LastMileManager:
    """Fetch the current GBFS snapshot and store it under the current hour."""

    def __init__(
        self,
        feeds_url: str,
        lang: str = "en",
        db_path: Optional[str] = None,
        timezone: str = "America/Los_Angeles",
    ):
        self.db_path = db_path
        self.utils = LastMileUtils(feeds_url=feeds_url, lang=lang, db_path=db_path)
        self.timezone = ZoneInfo(timezone)
        # Snapshots are bucketed to the local hour. Note that the hour repeats
        # once a year when DST falls back; the primary key means the second
        # reading is skipped rather than stored as a duplicate.
        now = datetime.now(self.timezone)
        self.snapshot_ts = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        self.timestamp = self.snapshot_ts.strftime("%Y-%m-%d-%H:00")

    def get_station_status(self) -> pd.DataFrame:
        """
        Current station status, including the availability flags GBFS
        publishes and this project previously discarded.
        """
        status = self.utils.load_feed_data("station_status", "stations")
        if status.empty:
            return status

        electric_ids = self.utils.electric_type_ids()
        out = pd.DataFrame({"station_id": status["station_id"].astype(str)})
        for column in (
            "num_bikes_available", "num_docks_available",
            "num_docks_disabled", "num_bikes_disabled",
        ):
            out[column] = (
                pd.to_numeric(status[column], errors="coerce")
                if column in status.columns
                else None
            )

        # Prefer the spec field; fall back to Lyft's extension where absent.
        spec_counts = None
        if "vehicle_types_available" in status.columns and electric_ids:
            spec_counts = status["vehicle_types_available"].map(
                lambda v: count_electric(v, electric_ids)
            )
        extension = (
            pd.to_numeric(status["num_ebikes_available"], errors="coerce")
            if "num_ebikes_available" in status.columns
            else None
        )
        if spec_counts is not None and extension is not None:
            out["num_ebikes_available"] = spec_counts.fillna(extension)
        elif spec_counts is not None:
            out["num_ebikes_available"] = spec_counts
        elif extension is not None:
            out["num_ebikes_available"] = extension
        else:
            out["num_ebikes_available"] = None

        for column in ("is_installed", "is_renting", "is_returning"):
            out[column] = (
                status[column].map(as_int_flag) if column in status.columns else None
            )
        out["last_reported"] = (
            pd.to_numeric(status["last_reported"], errors="coerce")
            if "last_reported" in status.columns
            else None
        )
        out["ts"] = self.snapshot_ts
        return out

    def get_bike_status(self) -> pd.DataFrame:
        """
        Current free-floating vehicles.

        GBFS asks publishers to rotate ``bike_id`` between trips for privacy,
        so these identifiers cannot be used to follow a vehicle over time.
        """
        if not self.utils.has_feed("free_bike_status"):
            return pd.DataFrame(columns=BIKE_COLUMNS)
        bikes = self.utils.load_feed_data("free_bike_status", "bikes")
        if bikes.empty:
            return pd.DataFrame(columns=BIKE_COLUMNS)

        out = pd.DataFrame({"bike_id": bikes["bike_id"].astype(str)})
        out["lat"] = pd.to_numeric(bikes.get("lat"), errors="coerce").round(5)
        out["lon"] = pd.to_numeric(bikes.get("lon"), errors="coerce").round(5)
        for column in ("is_reserved", "is_disabled"):
            out[column] = (
                bikes[column].map(as_int_flag) if column in bikes.columns else None
            )
        out["vehicle_type_id"] = (
            bikes["vehicle_type_id"].astype(str)
            if "vehicle_type_id" in bikes.columns
            else None
        )
        out["current_range_meters"] = pd.to_numeric(
            bikes.get("current_range_meters"), errors="coerce"
        )
        out["last_reported"] = (
            pd.to_numeric(bikes["last_reported"], errors="coerce")
            if "last_reported" in bikes.columns
            else None
        )
        out["ts"] = self.snapshot_ts
        return out

    def _write(self, table: str, columns: list[str], df: pd.DataFrame) -> int:
        if df.empty:
            print(f"  {table}: nothing to write")
            return 0
        rows = rows_from_frame(df, columns)
        written = self.utils.conn.insert_ignore(table, columns, rows)
        self.utils.conn.commit()
        return written

    def update_station_status(self, st_status: Optional[pd.DataFrame] = None) -> int:
        if st_status is None:
            st_status = self.get_station_status()
        written = self._write("station_status", STATION_COLUMNS, st_status)
        print(f"Station status: {written} rows written for {self.timestamp}")
        return written

    def update_bike_status(self, bk_status: Optional[pd.DataFrame] = None) -> int:
        if bk_status is None:
            bk_status = self.get_bike_status()
        written = self._write("bike_status", BIKE_COLUMNS, bk_status)
        print(f"Bike status: {written} rows written for {self.timestamp}")
        return written

    def update_data(self) -> bool:
        print(f"Updating data for {self.timestamp}...")
        self.update_station_status()
        self.update_bike_status()
        print("Data update completed successfully!")
        return True

    def __enter__(self) -> "LastMileManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.utils.disconnect()
        return False
