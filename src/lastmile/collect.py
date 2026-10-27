"""
Hourly GBFS collection, plus the slow-changing reference data.

Snapshots are bucketed to the local hour and inserted against the
``(entity, ts)`` primary key, so re-running the collector inside the same hour
is a no-op rather than a duplicate. Note the hour repeats once a year when DST
falls back; the key means the second reading is skipped.

Functions return row counts and leave printing to the CLI.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .constants import BIKE_COLUMNS, STATION_COLUMNS, TIMESTAMP_FORMAT
from .db import Db, rows_from_frame
from .db.schema import create_all
from .gbfs import GbfsClient, as_int_flag, count_electric
from .settings import get_settings

STATION_REF_COLUMNS = (
    "station_id",
    "name",
    "short_name",
    "region_id",
    "capacity",
    "lat",
    "lon",
    "region",
)
VEHICLE_TYPE_COLUMNS = (
    "vehicle_type_id",
    "form_factor",
    "propulsion_type",
    "max_range_meters",
)


def snapshot_hour() -> datetime:
    """The current local hour, naive, as stored in the ``ts`` columns."""
    now = datetime.now(ZoneInfo(get_settings().timezone))
    return now.replace(minute=0, second=0, microsecond=0, tzinfo=None)


# --- hourly snapshot --------------------------------------------------------


def station_status_frame(client: GbfsClient, ts: datetime) -> pd.DataFrame:
    """
    Current station status, including the availability flags GBFS
    publishes and this project previously discarded.
    """
    status = client.load_feed_data("station_status", "stations")
    if status.empty:
        return status

    electric_ids = client.electric_type_ids()
    out = pd.DataFrame({"station_id": status["station_id"].astype(str)})
    for column in (
        "num_bikes_available",
        "num_docks_available",
        "num_docks_disabled",
        "num_bikes_disabled",
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
    out["ts"] = ts
    return out


def bike_status_frame(client: GbfsClient, ts: datetime) -> pd.DataFrame:
    """
    Current free-floating vehicles.

    GBFS asks publishers to rotate ``bike_id`` between trips for privacy,
    so these identifiers cannot be used to follow a vehicle over time.
    """
    if not client.has_feed("free_bike_status"):
        return pd.DataFrame(columns=BIKE_COLUMNS)
    bikes = client.load_feed_data("free_bike_status", "bikes")
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
    out["ts"] = ts
    return out


def collect_snapshot(conn: Db, client: GbfsClient | None = None) -> dict:
    """Fetch and store one snapshot. Returns the hour and rows written."""
    client = client or GbfsClient()
    ts = snapshot_hour()
    stations = station_status_frame(client, ts)
    bikes = bike_status_frame(client, ts)
    station_rows = conn.insert_ignore(
        "station_status", STATION_COLUMNS, rows_from_frame(stations, STATION_COLUMNS)
    )
    bike_rows = conn.insert_ignore(
        "bike_status", BIKE_COLUMNS, rows_from_frame(bikes, BIKE_COLUMNS)
    )
    return {
        "timestamp": ts.strftime(TIMESTAMP_FORMAT),
        "station_rows": station_rows,
        "bike_rows": bike_rows,
    }


# --- reference data ---------------------------------------------------------


def refresh_stations(conn: Db, client: GbfsClient) -> int:
    """
    Upsert station metadata joined with its region name.

    Systems that are entirely free-floating publish an empty
    ``station_information`` feed, which is valid GBFS and not an error.
    """
    st_info = client.load_feed_data("station_information", "stations")
    if st_info.empty:
        return 0

    for column in ("station_id", "name", "short_name", "region_id", "capacity", "lat", "lon"):
        if column not in st_info.columns:
            st_info[column] = None
    st_info = st_info[
        ["station_id", "name", "short_name", "region_id", "capacity", "lat", "lon"]
    ].drop_duplicates(subset=["station_id"])

    stations = st_info
    if client.has_feed("system_regions"):
        regions = client.load_feed_data("system_regions", "regions")
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

    conn.upsert(
        "stations",
        STATION_REF_COLUMNS,
        rows_from_frame(stations, STATION_REF_COLUMNS),
        conflict=["station_id"],
    )
    return len(stations)


def refresh_vehicle_types(conn: Db, client: GbfsClient) -> int:
    """
    Upsert the ``vehicle_types`` feed.

    Needed to interpret ``vehicle_type_id`` and to count e-bikes the way the
    spec intends, rather than relying on Lyft's ``num_ebikes_available``.
    """
    types = client.vehicle_types()
    if types.empty:
        return 0
    conn.upsert(
        "vehicle_types",
        VEHICLE_TYPE_COLUMNS,
        rows_from_frame(types, VEHICLE_TYPE_COLUMNS),
        conflict=["vehicle_type_id"],
    )
    return len(types)


def init_db(conn: Db, client: GbfsClient | None = None) -> dict:
    """Create the schema and load reference data. Safe to run repeatedly."""
    create_all(conn)
    client = client or GbfsClient()
    return {
        "stations": refresh_stations(conn, client),
        "vehicle_types": refresh_vehicle_types(conn, client),
    }


def is_initialized(conn: Db) -> bool:
    """True when the schema exists and station metadata is loaded."""
    for table in ("stations", "station_status", "bike_status"):
        if not conn.has_table(table):
            return False
    return conn.count("stations") > 0
