"""
The small hand-built lake behind the query and metrics tests.

Three stations, one per status the rollups care about (empty, full, healthy),
in two regions, with two vehicle types of which one is electric, plus three
free-floating vehicles in the first hour. ``seed`` fills a lake with 48 hourly
snapshots of it; ``key`` names those hours.
"""

from __future__ import annotations

from datetime import datetime, timedelta

STATION_COLUMNS = ("station_id", "name", "region_id", "capacity", "lat", "lon")
STATUS_COLUMNS = (
    "station_id",
    "ts",
    "num_vehicles_available",
    "num_docks_available",
)
AVAILABLE_COLUMNS = ("station_id", "ts", "vehicle_type_id", "count")
VEHICLE_COLUMNS = (
    "vehicle_id",
    "ts",
    "lat",
    "lon",
    "is_disabled",
    "is_reserved",
    "current_range_meters",
)

START = datetime(2026, 10, 28, 6)
# Three stations, deliberately covering each status the rollup counts.
STATIONS = [
    # (id, name, region_id, capacity, lat, lon, vehicles, docks)
    ("a", "Alpha", "n", 20, 30.2700, -97.7350, 0, 20),  # empty
    ("b", "Bravo", "n", 20, 30.2720, -97.7400, 20, 0),  # full
    ("c", "Delta", "s", 20, 30.2900, -97.7500, 10, 10),  # healthy
]
REGIONS = [("n", "North"), ("s", "South")]
# Two types, one electric, so the derived split has something to find.
VEHICLE_TYPES = [("classic", "human"), ("ebike", "electric_assist")]


def seed(lake):
    """Fill a lake with 48 hourly snapshots of three stations across two days."""
    lake.upsert("system_regions", ("region_id", "name"), REGIONS)
    lake.upsert("vehicle_types", ("vehicle_type_id", "propulsion_type"), VEHICLE_TYPES)
    lake.upsert(
        "station_information",
        STATION_COLUMNS,
        [
            (sid, name, region, cap, lat, lon)
            for sid, name, region, cap, lat, lon, _, _ in STATIONS
        ],
    )
    status, available = [], []
    for offset in range(48):
        ts = START + timedelta(hours=offset)
        for sid, _, _, _, _, _, vehicles, docks in STATIONS:
            status.append((sid, ts, vehicles, docks))
            electric = min(vehicles, 2)
            available.append((sid, ts, "ebike", electric))
            available.append((sid, ts, "classic", vehicles - electric))
    lake.insert_ignore("station_status", STATUS_COLUMNS, status)
    lake.insert_ignore("station_vehicle_types_available", AVAILABLE_COLUMNS, available)
    lake.insert_ignore(
        "vehicle_status",
        VEHICLE_COLUMNS,
        [
            ("v1", START, 30.2705, -97.7355, 0, 0, 12000.0),
            ("v2", START, 30.2800, -97.7450, 1, 0, 1200.0),
            ("v3", START, 30.2810, -97.7460, 0, 1, None),
        ],
    )


def key(offset: int) -> str:
    return (START + timedelta(hours=offset)).strftime("%Y-%m-%d-%H:00")
