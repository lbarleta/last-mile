"""
The read layer, against a seeded lake.

Covers the two joins the spec-aligned schema introduced — region names out of
``system_regions`` rather than denormalized onto each station, and electric
availability summed out of ``station_vehicle_types_available`` rather than read
from a column — plus the aggregates the dashboard's three views are built on
and the DuckDB-specific SQL fragments underneath them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from lastmile import db
from lastmile.db import queries

STATION_COLUMNS = ("station_id", "name", "region_id", "capacity", "lat", "lon")
STATUS_COLUMNS = (
    "station_id",
    "ts",
    "num_vehicles_available",
    "num_docks_available",
)
AVAILABLE_COLUMNS = ("station_id", "ts", "vehicle_type_id", "count")
VEHICLE_COLUMNS = ("vehicle_id", "ts", "lat", "lon", "is_disabled", "is_reserved",
                   "current_range_meters")

START = datetime(2026, 10, 28, 6)
# Three stations, deliberately covering each status the rollup counts.
STATIONS = [
    # (id, name, region_id, capacity, lat, lon, vehicles, docks)
    ("a", "Alpha", "n", 20, 30.2700, -97.7350, 0, 20),   # empty
    ("b", "Bravo", "n", 20, 30.2720, -97.7400, 20, 0),   # full
    ("c", "Delta", "s", 20, 30.2900, -97.7500, 10, 10),  # healthy
]
REGIONS = [("n", "North"), ("s", "South")]
# Two types, one electric, so the derived split has something to find.
VEHICLE_TYPES = [("classic", "human"), ("ebike", "electric_assist")]


@pytest.fixture
def seeded(lake):
    """A lake holding 48 hourly snapshots of three stations across three days."""
    lake.upsert("system_regions", ("region_id", "name"), REGIONS)
    lake.upsert(
        "vehicle_types", ("vehicle_type_id", "propulsion_type"), VEHICLE_TYPES
    )
    lake.upsert(
        "station_information",
        STATION_COLUMNS,
        [(sid, name, region, cap, lat, lon)
         for sid, name, region, cap, lat, lon, _, _ in STATIONS],
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
    lake.insert_ignore(
        "station_vehicle_types_available", AVAILABLE_COLUMNS, available
    )
    lake.insert_ignore(
        "vehicle_status",
        VEHICLE_COLUMNS,
        [
            ("v1", START, 30.2705, -97.7355, 0, 0, 12000.0),
            ("v2", START, 30.2800, -97.7450, 1, 0, 1200.0),
            ("v3", START, 30.2810, -97.7460, 0, 1, None),
        ],
    )
    return lake


def key(offset: int) -> str:
    return (START + timedelta(hours=offset)).strftime("%Y-%m-%d-%H:00")


# --- what exists -----------------------------------------------------------


def test_timestamp_bounds(seeded):
    assert queries.get_timestamp_bounds(seeded) == (key(0), key(47))
    assert queries.get_latest_timestamp(seeded) == key(47)


def test_bounds_of_an_empty_lake(lake):
    assert queries.get_timestamp_bounds(lake) == (None, None)
    assert queries.get_latest_timestamp(lake) is None


def test_snapshot_dates_and_hours(seeded):
    # 48 hours from 06:00 spans three calendar dates.
    assert queries.list_snapshot_dates(seeded) == [
        "2026-10-28",
        "2026-10-29",
        "2026-10-30",
    ]
    hours = queries.list_snapshot_hours_for_date(seeded, "2026-10-28")
    assert hours[0] == "06:00"
    assert hours[-1] == "23:00"
    assert len(hours) == 18


def test_list_regions_orders_by_station_count(seeded):
    assert queries.list_regions(seeded) == ["North", "South"]


# --- snapshots -------------------------------------------------------------


def test_station_snapshot_joins_metadata(seeded):
    frame = queries.get_station_snapshot_at(seeded, key(0)).set_index("station_id")
    assert len(frame) == 3
    assert set(frame["name"]) == {"Alpha", "Bravo", "Delta"}
    assert set(frame["timestamp"]) == {key(0)}
    # The region name comes from system_regions via region_id, not a column.
    assert frame.loc["a", "region"] == "North"
    assert frame.loc["c", "region"] == "South"


def test_station_snapshot_derives_electric_availability(seeded):
    """
    GBFS has no electric count. It is summed from the per-type breakdown
    against vehicle_types.propulsion_type, which is the spec's own route.
    """
    frame = queries.get_station_snapshot_at(seeded, key(0)).set_index("station_id")
    assert frame.loc["b", "num_vehicles_available"] == 20
    assert frame.loc["b", "num_vehicles_available_electric"] == 2
    # An empty station has no electric vehicles and no breakdown row to find.
    assert frame.loc["a", "num_vehicles_available_electric"] == 0


def test_a_station_with_no_breakdown_reads_zero_not_null(lake):
    """A publisher may omit vehicle_types_available entirely."""
    lake.upsert("station_information", ("station_id", "name"), [("a", "Alpha")])
    lake.insert_ignore("station_status", STATUS_COLUMNS, [("a", START, 5, 15)])
    frame = queries.get_station_snapshot_at(lake, key(0))
    assert frame.iloc[0]["num_vehicles_available_electric"] == 0


def test_region_without_a_name_falls_back_to_unknown(lake):
    lake.upsert(
        "station_information",
        ("station_id", "name", "region_id"),
        [("a", "Alpha", "ghost")],
    )
    lake.insert_ignore("station_status", STATUS_COLUMNS, [("a", START, 5, 15)])
    frame = queries.get_station_snapshot_at(lake, key(0))
    assert frame.iloc[0]["region"] == "Unknown"


def test_latest_station_snapshot(seeded):
    frame = queries.get_latest_station_snapshot(seeded)
    assert set(frame["timestamp"]) == {key(47)}


def test_free_bike_counts(seeded):
    counts = queries.get_free_bike_counts(seeded, key(0), low_range_meters=5000)
    assert counts == {"total": 3, "disabled": 1, "reserved": 1, "low_range": 1}


def test_free_bike_snapshot_defaults_to_latest(seeded):
    frame = queries.get_free_bike_snapshot(seeded)
    assert len(frame) == 3
    assert set(frame["timestamp"]) == {key(0)}


# --- aggregates ------------------------------------------------------------


def test_availability_timeseries_counts_each_status(seeded):
    frame = queries.get_availability_timeseries(seeded)
    assert len(frame) == 48
    first = frame.iloc[0]
    assert first["timestamp"] == key(0)
    assert first["bikes_available"] == 30
    assert first["docks_available"] == 30
    assert first["station_count"] == 3
    # The four states are mutually exclusive and sum to the station count.
    assert (first["empty_stations"], first["full_stations"]) == (1, 1)
    assert (first["low_stations"], first["healthy_stations"]) == (0, 1)
    # Electric availability is summed from the per-type breakdown: two each at
    # the full and healthy stations, none at the empty one.
    assert first["ebikes_available"] == 4
    # num_vehicles_available includes electric, so classic is the difference.
    assert first["classic_available"] == 30 - first["ebikes_available"]


def test_availability_timeseries_window_bounds_the_electric_join(seeded):
    """
    The electric CTE repeats the outer time filter rather than scanning all
    history, so it has to agree with the outer query hour for hour.
    """
    windowed = queries.get_availability_timeseries(
        seeded, since=key(10), until=key(12)
    )
    assert list(windowed["timestamp"]) == [key(10), key(11), key(12)]
    assert (windowed["ebikes_available"] == 4).all()


def test_low_threshold_uses_float_division(lake):
    """
    An integer division would floor the bike share to 0 and call this empty.

    Three bikes against 20 docks is 13% — low, not healthy and not empty.
    """
    lake.upsert("station_information", ("station_id", "name"), [("a", "Alpha")])
    lake.insert_ignore("station_status", STATUS_COLUMNS, [("a", START, 3, 20)])
    row = queries.get_availability_timeseries(lake).iloc[0]
    assert (row["empty_stations"], row["low_stations"]) == (0, 1)
    assert (row["healthy_stations"], row["full_stations"]) == (0, 0)


def test_availability_timeseries_filters(seeded):
    by_region = queries.get_availability_timeseries(seeded, region="South")
    assert (by_region["station_count"] == 1).all()

    windowed = queries.get_availability_timeseries(
        seeded, since=key(10), until=key(12)
    )
    assert list(windowed["timestamp"]) == [key(10), key(11), key(12)]

    at_noon = queries.get_availability_timeseries(seeded, hour_of_day="12")
    assert list(at_noon["timestamp"]) == [key(6), key(30)]


def test_free_bike_timeseries(seeded):
    frame = queries.get_free_bike_timeseries(seeded)
    assert list(frame["timestamp"]) == [key(0)]
    assert frame.iloc[0]["free_floating"] == 3


def test_station_reliability_binds_where_and_having(seeded):
    """The min_hours parameter is bound after the filters, in HAVING."""
    frame = queries.get_station_reliability(seeded, since=key(0), min_hours=48)
    by_station = frame.set_index("station_id")
    assert set(by_station.index) == {"a", "b", "c"}
    assert by_station.loc["a", "pct_empty"] == 100.0
    assert by_station.loc["b", "pct_full"] == 100.0
    assert by_station.loc["c", "pct_failure"] == 0.0

    # Nothing has 49 hours of history, so the threshold excludes everything.
    assert queries.get_station_reliability(seeded, min_hours=49).empty


def test_station_reliability_filters_by_region(seeded):
    frame = queries.get_station_reliability(seeded, region="South", min_hours=1)
    assert list(frame["station_id"]) == ["c"]


# --- the problematic-station rule -----------------------------------------


def test_problematic_stations(seeded):
    frame = queries.get_problematic_stations(seeded, key(8), lookback_hours=3)
    by_station = frame.set_index("station_id")
    assert set(by_station.index) == {"a", "b"}
    assert by_station.loc["a", "issue"] == "Empty"
    assert by_station.loc["b", "issue"] == "Full"
    assert by_station.loc["a", "hours_problematic"] == 3


def test_problematic_stations_suggest_a_nearby_backup(seeded):
    frame = queries.get_problematic_stations(seeded, key(8), backup_radius_m=1000)
    backup = frame.set_index("station_id").loc["a", "backup_station"]
    # Delta is the only station that is neither empty nor full.
    assert backup == "Delta" or backup is None


def test_night_hours_are_not_ops_hours(seeded):
    """The lookback only counts daytime hours, so 3am flags nothing."""
    assert queries.get_problematic_stations(seeded, key(21)).empty


def test_problematic_timeseries(seeded):
    frame = queries.get_problematic_timeseries(seeded, since=key(4))
    assert not frame.empty
    daytime = frame[frame["timestamp"] == key(8)].iloc[0]
    assert daytime["empty_stations"] == 1
    assert daytime["full_stations"] == 1
    assert daytime["station_count"] == 3


# --- timestamp helpers -----------------------------------------------------


def test_cutoff_timestamp():
    assert queries.cutoff_timestamp(6, None, key(10)) == key(4)
    assert queries.cutoff_timestamp(None, None, key(10)) is None


def test_lookback_timestamps():
    assert queries.lookback_timestamps(key(10), 3) == [key(10), key(9), key(8)]


def test_previous_hour():
    assert queries.previous_hour_timestamp(key(10)) == key(9)


def test_ops_day_hour():
    assert queries.is_ops_day_hour(key(2))       # 08:00
    assert not queries.is_ops_day_hour(key(21))  # 03:00


def test_system_info_is_absent_until_collected(lake):
    assert queries.get_system_info(lake) is None
    assert queries.stored_timezone(lake) is None


def test_distance_to_nearest_station(seeded):
    stations = queries.get_station_snapshot_at(seeded, key(0))
    bikes = queries.get_free_bike_snapshot(seeded, key(0))
    distance = queries.avg_distance_to_nearest_station_m(stations, bikes)
    assert 0 < distance < 2000


def test_distance_is_none_without_bikes(seeded):
    stations = queries.get_station_snapshot_at(seeded, key(0))
    empty = queries.get_free_bike_snapshot(seeded, key(1))
    assert queries.avg_distance_to_nearest_station_m(stations, empty) is None


def test_a_bad_parameter_count_is_rejected(seeded):
    """
    DuckDB takes ``?`` placeholders natively, so it catches this itself.

    The old wrapper had to count them by hand while rewriting them into
    SQLAlchemy's named binds.
    """
    import duckdb

    with pytest.raises(duckdb.ProgrammingError, match="not provided"):
        seeded.fetchall(
            "SELECT * FROM station_information WHERE station_id = ? AND name = ?", ("a",)
        )


def test_keys_round_trip_through_a_frame(seeded):
    frame = seeded.read_sql("SELECT ts FROM station_status ORDER BY ts LIMIT 1")
    assert list(db.keys_from_series(frame["ts"])) == [key(0)]
