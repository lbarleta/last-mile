"""One-time setup: create tables and load the slow-changing reference data."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .engine import rows_from_frame
from .schema import create_all, ensure_indexes as _ensure_indexes
from .utils import LastMileUtils


class LastMileSetup:
    """Create the schema and populate stations and vehicle types."""

    def __init__(
        self,
        feeds_url: str,
        lang: str = "en",
        db_path: Optional[str] = None,
    ):
        self.utils = LastMileUtils(feeds_url=feeds_url, lang=lang, db_path=db_path)

    def setup_stations_table(self) -> pd.DataFrame:
        """
        Load station metadata joined with its region name.

        Systems that are entirely free-floating publish an empty
        ``station_information`` feed, which is valid GBFS and not an error.
        """
        print("Setting up stations table...")
        st_info = self.utils.load_feed_data(name="station_information", key="stations")
        if st_info.empty:
            print("  station_information is empty (free-floating system)")
            return st_info

        for column in ("station_id", "name", "short_name", "region_id", "capacity", "lat", "lon"):
            if column not in st_info.columns:
                st_info[column] = None
        st_info = st_info[
            ["station_id", "name", "short_name", "region_id", "capacity", "lat", "lon"]
        ].drop_duplicates(subset=["station_id"])

        stations = st_info
        if self.utils.has_feed("system_regions"):
            regions = self.utils.load_feed_data(name="system_regions", key="regions")
            if not regions.empty:
                regions = regions.drop_duplicates(subset=["region_id"])
                stations = pd.merge(
                    st_info,
                    regions[["region_id", "name"]].rename(columns={"name": "region"}),
                    on="region_id",
                    how="left",
                )
        if "region" not in stations.columns:
            stations["region"] = None

        stations["lat"] = pd.to_numeric(stations["lat"], errors="coerce").round(5)
        stations["lon"] = pd.to_numeric(stations["lon"], errors="coerce").round(5)

        columns = [
            "station_id", "name", "short_name", "region_id",
            "capacity", "lat", "lon", "region",
        ]
        self.utils.conn.upsert(
            "stations", columns, rows_from_frame(stations, columns),
            conflict=["station_id"],
        )
        self.utils.conn.commit()
        print(f"Stations table populated with {len(stations)} stations")
        return stations

    def setup_vehicle_types(self) -> pd.DataFrame:
        """
        Load the ``vehicle_types`` feed.

        Needed to interpret ``vehicle_type_id`` and to count e-bikes the way
        the spec intends, rather than relying on Lyft's ``num_ebikes_available``.
        """
        types = self.utils.vehicle_types()
        if types.empty:
            print("No vehicle_types feed published")
            return types
        columns = [
            "vehicle_type_id", "form_factor", "propulsion_type", "max_range_meters",
        ]
        self.utils.conn.upsert(
            "vehicle_types", columns, rows_from_frame(types, columns),
            conflict=["vehicle_type_id"],
        )
        self.utils.conn.commit()
        print(f"Loaded {len(types)} vehicle types")
        return types

    def create_tables(self, overwrite: bool = False) -> None:
        """Create every table and load reference data."""
        print("Creating database tables...")
        create_all(self.utils.conn)
        if self.verify_setup() and not overwrite:
            print("Tables already exist and stations are populated.")
            return
        self.setup_stations_table()
        self.setup_vehicle_types()
        print("All database tables created successfully")

    def ensure_indexes(self) -> None:
        _ensure_indexes(self.utils.conn)
        print("Database indexes verified")

    def verify_setup(self) -> bool:
        """True when the schema exists and station metadata is loaded."""
        conn = self.utils.conn
        for table in ("stations", "station_status", "bike_status"):
            if not conn.has_table(table):
                print(f"Table {table} not found")
                return False
        count = conn.fetchone("SELECT COUNT(*) FROM stations")[0]
        print(f"Found {count} stations in database")
        return count > 0

    def __enter__(self) -> "LastMileSetup":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.utils.disconnect()
        return False
