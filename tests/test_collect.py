"""
Collection end to end: feed in, Parquet out, on either spec version.

Everything here runs against recorded feeds and a tmp lake, so it covers the
whole path the hourly cron entry takes without touching the network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lastmile import collect
from lastmile.db import queries, schema, setup

DOCKED = ("v23", "v30")
FREE_FLOATING = ("freefloat_v23", "freefloat_v30")


# --- reference data --------------------------------------------------------


@pytest.mark.parametrize("feed_set", DOCKED)
def test_init_db_loads_every_reference_feed(lake, gbfs_client, feed_set):
    results = setup.init_db(lake, gbfs_client(feed_set))["reference"]
    # Austin advertises geofencing_zones with zero features: one empty capture,
    # recording that; the documents side is covered in test_geofencing.py.
    geofencing = results.pop("geofencing_zones")
    assert geofencing["captures"] == 1
    assert geofencing["features"] == 0
    assert {name: counts["total"] for name, counts in results.items()} == {
        "system_information": 1,
        "gbfs_versions": 3,
        "system_regions": 0,
        "system_pricing_plans": 2,
        "system_alerts": 0,
        "vehicle_types": 3,
        "station_information": 3,
    }
    assert setup.is_initialized(lake)


@pytest.mark.parametrize("feed_set", DOCKED)
def test_init_db_records_the_system(lake, gbfs_client, feed_set):
    client = gbfs_client(feed_set)
    result = setup.init_db(lake, client)
    info = queries.get_system_info(lake)
    assert info["system_id"] == "austin"
    assert info["timezone"] == "America/Chicago"
    assert info["gbfs_version"] == client.version
    # What the CLI prints comes back from init-db; it never asks the client.
    assert result["system"]["name"] == info["name"]
    assert result["system"]["gbfs_version"] == client.version
    assert result["timezone"] == "America/Chicago"


@pytest.mark.parametrize("feed_set", DOCKED)
def test_the_full_feed_is_stored_not_just_what_the_dashboard_uses(
    lake, gbfs_client, feed_set
):
    setup.init_db(lake, gbfs_client(feed_set))
    station = lake.read_sql(
        "SELECT * FROM station_information WHERE station_id = '1'"
    ).iloc[0]
    assert station["address"] == "E 10th/Red River"
    assert station["is_charging_station"] == 0
    assert "creditcard" in station["rental_methods"]

    plan = lake.read_sql(
        "SELECT * FROM system_pricing_plans WHERE plan_id = '182'"
    ).iloc[0]
    assert plan["currency"] == "USD"
    assert plan["per_min_pricing"]


@pytest.mark.parametrize("feed_set", DOCKED)
def test_refreshing_reference_data_logs_nothing_when_it_has_not_changed(
    lake, gbfs_client, feed_set
):
    client = gbfs_client(feed_set)
    setup.init_db(lake, client)
    logged = lake.count("station_information_log")
    results = collect.refresh_reference_data(lake, client)
    assert all(
        counts["changed"] == 0
        for name, counts in results.items()
        if name != "geofencing_zones"  # documents, not a tracked table
    )
    assert not results["geofencing_zones"]["captured"]
    assert lake.count("station_information_log") == logged


@pytest.mark.parametrize("feed_set", DOCKED)
def test_a_changed_station_lands_in_the_log(lake, gbfs_client, feed_set, monkeypatch):
    client = gbfs_client(feed_set)
    setup.init_db(lake, client)

    stations = client.station_information()
    renamed = stations.assign(
        name=stations["name"].mask(stations["station_id"] == "1", "Renamed")
    )
    monkeypatch.setattr(client, "station_information", lambda: renamed)
    results = collect.refresh_reference_data(lake, client)

    assert results["station_information"]["changed"] == 1
    log = lake.fetchall(
        "SELECT station_id, name, change FROM station_information_log "
        "WHERE change = 'changed'"
    )
    assert log == [("1", "Renamed", "changed")]
    # And the current state is the new one.
    assert (
        lake.fetchone("SELECT name FROM station_information WHERE station_id = '1'")[0]
        == "Renamed"
    )


# --- hourly snapshots ------------------------------------------------------


@pytest.mark.parametrize("feed_set", DOCKED)
def test_collect_snapshot_writes_every_status_table(lake, gbfs_client, feed_set):
    client = gbfs_client(feed_set)
    setup.init_db(lake, client)
    result = collect.collect_snapshot(lake, client)
    assert result["rows"] == {
        "station_status": 3,
        # three stations x three vehicle types
        "station_vehicle_types_available": 9,
        "station_vehicle_docks_available": 3,
        "vehicle_status": 0,
    }
    assert queries.get_latest_timestamp(lake) == result["timestamp"]


@pytest.mark.parametrize("feed_set", DOCKED)
def test_collecting_the_same_hour_twice_adds_nothing(lake, gbfs_client, feed_set):
    """The guarantee the cron entry depends on."""
    client = gbfs_client(feed_set)
    setup.init_db(lake, client)
    collect.collect_snapshot(lake, client)
    again = collect.collect_snapshot(lake, client)
    assert set(again["rows"].values()) == {0}
    assert lake.count("station_status") == 3


@pytest.mark.parametrize("feed_set", DOCKED)
def test_the_per_type_breakdown_adds_up(lake, gbfs_client, feed_set):
    """Electric availability is derived from it, so it has to reconcile."""
    client = gbfs_client(feed_set)
    setup.init_db(lake, client)
    collect.collect_snapshot(lake, client)
    row = lake.fetchone(
        """
        SELECT
            (SELECT SUM(num_vehicles_available) FROM station_status),
            (SELECT SUM(count) FROM station_vehicle_types_available)
        """
    )
    assert row[0] == row[1]


@pytest.mark.parametrize("feed_set", FREE_FLOATING)
def test_collects_free_floating_vehicles(lake, gbfs_client, feed_set):
    client = gbfs_client(feed_set)
    setup.init_db(lake, client)
    result = collect.collect_snapshot(lake, client)
    assert result["rows"]["vehicle_status"] == 3
    assert result["rows"]["station_status"] == 0
    frame = queries.get_free_bike_snapshot(lake)
    assert len(frame) == 3
    assert set(frame["vehicle_type_id"]) == {"scooter", "classic"}


@pytest.mark.parametrize("feed_set", FREE_FLOATING)
def test_a_station_less_system_still_counts_as_initialized(lake, gbfs_client, feed_set):
    """
    A free-floating system publishes no stations, which is valid GBFS.

    Keying "initialized" on station rows would refuse to ever collect one.
    """
    setup.init_db(lake, gbfs_client(feed_set))
    assert lake.count("station_information") == 0
    assert setup.is_initialized(lake)


def test_stations_keep_their_region_id_for_the_join(lake, gbfs_client, monkeypatch):
    """
    Region names live in system_regions, not denormalized onto each station.

    Austin publishes no regions, so this fakes one to cover the join.
    """
    import pandas as pd

    client = gbfs_client("v30")
    stations = client.station_information().assign(region_id="c")
    monkeypatch.setattr(client, "station_information", lambda: stations)
    monkeypatch.setattr(
        client,
        "system_regions",
        lambda: pd.DataFrame({"region_id": ["c"], "name": ["Central"]}),
    )
    setup.init_db(lake, client)
    assert queries.list_regions(lake) == ["Central"]


def test_empty_regions_leave_stations_unregioned(lake, gbfs_client):
    """
    Austin publishes system_regions as an empty array, which is valid GBFS.

    Stations keep a NULL region_id and the dashboard's filter offers the single
    synthetic "Unknown" bucket.
    """
    setup.init_db(lake, gbfs_client("v30"))
    assert lake.fetchone("SELECT region_id FROM station_information LIMIT 1")[0] is None
    assert queries.list_regions(lake) == ["Unknown"]


def test_nothing_is_written_outside_the_declared_tables(lake, gbfs_client):
    setup.init_db(lake, gbfs_client("v30"))
    collect.collect_snapshot(lake, gbfs_client("v30"))
    written = {name for name in schema.TABLE_NAMES if lake.count(name)}
    assert written <= set(schema.TABLE_NAMES)
    assert lake.count("weather") == 0


# --- snapshot hour ---------------------------------------------------------


def test_snapshot_hour_is_the_current_utc_hour():
    hour = collect.snapshot_hour()
    assert (hour.minute, hour.second, hour.microsecond) == (0, 0, 0)
    assert hour.tzinfo == UTC


def at(instant: datetime):
    """Pin the collector's clock to one UTC instant."""
    return lambda: instant


def test_the_snapshot_key_is_reported_in_the_system_zone(
    lake, gbfs_client, monkeypatch
):
    """Collect stamps UTC; what it reports back is the lake's local label."""
    client = gbfs_client("v30")  # Austin, America/Chicago
    setup.init_db(lake, client)
    monkeypatch.setattr(collect, "now", at(datetime(2026, 7, 1, 15, 20, tzinfo=UTC)))
    result = collect.collect_snapshot(lake, client)
    assert result["timestamp"] == "2026-07-01-10:00"
    assert queries.get_latest_timestamp(lake) == "2026-07-01-10:00"


def test_both_fall_back_readings_are_kept(lake, gbfs_client, monkeypatch):
    """
    America/Chicago reads 01:00 twice on 2026-11-01. Each is its own hour in
    UTC, so each is stored; the metrics see two rows under one label.
    """
    client = gbfs_client("v30")
    setup.init_db(lake, client)
    for utc_hour in (6, 7):
        monkeypatch.setattr(
            collect, "now", at(datetime(2026, 11, 1, utc_hour, 5, tzinfo=UTC))
        )
        result = collect.collect_snapshot(lake, client)
        assert result["timestamp"] == "2026-11-01-01:00"
        assert result["rows"]["station_status"] == 3
    assert lake.count("station_status") == 6
    assert queries.list_snapshot_hours_for_date(lake, "2026-11-01") == ["01:00"]


def test_the_spring_forward_gap_is_just_a_missing_label(lake, gbfs_client, monkeypatch):
    """02:00 never happens on 2026-03-08 in Chicago; 01:00 and 03:00 are adjacent."""
    client = gbfs_client("v30")
    setup.init_db(lake, client)
    for utc_hour in (7, 8):
        monkeypatch.setattr(
            collect, "now", at(datetime(2026, 3, 8, utc_hour, tzinfo=UTC))
        )
        collect.collect_snapshot(lake, client)
    assert queries.list_snapshot_hours_for_date(lake, "2026-03-08") == [
        "01:00",
        "03:00",
    ]


def test_init_db_applies_the_system_timezone_to_the_lake(lake, gbfs_client):
    """The dashboard has no feed client; it reads what collection recorded."""
    assert lake.timezone == "UTC"
    setup.init_db(lake, gbfs_client("v30"))
    assert lake.timezone == "America/Chicago"


def test_reference_changes_are_readable(lake, gbfs_client):
    setup.init_db(lake, gbfs_client("v30"))
    changes = queries.get_reference_changes(lake, "station_information")
    assert len(changes) == 3
    assert set(changes["change"]) == {"added"}
    assert changes["observed_at"].map(lambda v: v.tzinfo is not None).all()
