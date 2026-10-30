"""
Feed parsing, across both spec versions.

The point of most of these is the same one: a 2.3 feed and a 3.0 feed for the
same system have to come out of the client identically, under the 3.0 names,
because the warehouse and everything above it are written against those.
``test_specs_agree`` is what would catch a regression in any individual rename.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lastmile.gbfs import as_epoch, as_int_flag, joined, key_of, localized

DOCKED = ("v23", "v30")
FREE_FLOATING = ("freefloat_v23", "freefloat_v30")


# --- value normalization ---------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("E 10th/Red River", "E 10th/Red River"),
        ([{"text": "Main St", "language": "en"}], "Main St"),
        ([{"text": "Calle Mayor", "language": "es"},
          {"text": "Main St", "language": "en"}], "Main St"),
        # No match falls back to the first translation rather than nothing.
        ([{"text": "Calle Mayor", "language": "es"}], "Calle Mayor"),
        ([], None),
        (None, None),
    ],
)
def test_localized_collapses_both_shapes(value, expected):
    assert localized(value, "en") == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1793295300, 1793295300),
        # GBFS 3 moved every timestamp to RFC 3339, always with an offset.
        ("2026-10-29T17:35:00Z", 1793295300),
        ("2026-10-29T12:35:00-05:00", 1793295300),
        ("2026-10-29T17:35:00.824Z", 1793295300),
        (None, None),
        ("", None),
        ("not a time", None),
    ],
)
def test_as_epoch_reads_either_spec(value, expected):
    assert as_epoch(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, 1), (False, 0), (1, 1), (0, 0), ("1", 1), (None, None), ("yes", None)],
)
def test_as_int_flag(value, expected):
    assert as_int_flag(value) == expected


def test_joined_flattens_scalar_arrays():
    assert joined(["key", "creditcard"]) == "key, creditcard"
    assert joined([]) is None
    assert joined(None) is None


def test_key_of_sorts_so_the_same_set_reads_the_same():
    """
    vehicle_docks_available keys on a *set* of types, with no promised order.

    Sorting is what keeps one group of docks looking like one row hour to hour.
    """
    assert key_of(["EFIT", "BOOST", "FIT"]) == key_of(["FIT", "EFIT", "BOOST"])
    assert key_of(["EFIT", "BOOST"]) == "BOOST, EFIT"


# --- discovery -------------------------------------------------------------


def test_detects_version_from_the_document(gbfs_client):
    assert gbfs_client("v23").version == "2.3"
    assert gbfs_client("v30").version == "3.0"


def test_infers_version_when_the_document_omits_it(feed_transport, tmp_path):
    """Austin's real 2.3 gbfs.json has no `version`; the language envelope does."""
    import json
    import shutil

    from lastmile.gbfs import GbfsClient

    transport = feed_transport("v23")
    stripped = tmp_path / "feeds"
    shutil.copytree(transport.directory, stripped)
    payload = json.loads((stripped / "gbfs.json").read_text())
    del payload["version"]
    (stripped / "gbfs.json").write_text(json.dumps(payload))
    transport.directory = stripped
    assert GbfsClient(feeds_url="gbfs.json").version == "2.3"


def test_resolves_renamed_feeds_under_either_name(gbfs_client):
    """free_bike_status became vehicle_status; the 3.0 name is canonical here."""
    assert gbfs_client("freefloat_v23").has_feed("vehicle_status")
    assert gbfs_client("freefloat_v30").has_feed("vehicle_status")
    assert not gbfs_client("v30").has_feed("vehicle_status")


def test_missing_feed_names_what_is_available(gbfs_client):
    with pytest.raises(KeyError, match="station_status"):
        gbfs_client("v30").get_feed_url("vehicle_status")


# --- normalized views ------------------------------------------------------


@pytest.mark.parametrize("feed_set", DOCKED)
def test_system_information(gbfs_client, feed_set):
    info = gbfs_client(feed_set).system_information()
    assert info["system_id"] == "austin"
    assert info["name"] == "austin"
    # The field that decides which local hour a snapshot is filed under.
    assert info["timezone"] == "America/Chicago"
    assert info["email"] == "bikeshare@capmetro.org"
    # 2.x publishes a single `language`, 3.x a `languages` list.
    assert "en" in info["languages"]


@pytest.mark.parametrize("feed_set", FREE_FLOATING)
def test_localized_system_name(gbfs_client, feed_set):
    info = gbfs_client(feed_set).system_information()
    assert info["name"] == "Riverside Scooters"


@pytest.mark.parametrize("feed_set", DOCKED)
def test_station_information(gbfs_client, feed_set):
    stations = gbfs_client(feed_set).station_information().set_index("station_id")
    assert list(stations.index) == ["1", "2", "3"]
    first = stations.loc["1"]
    # 3.0 publishes these as [{text, language}]; 2.3 as plain strings.
    assert first["name"] == "E 10th/Red River"
    assert first["short_name"] == "1"
    assert first["capacity"] == 15
    assert first["address"] == "E 10th/Red River"
    assert first["lat"] == pytest.approx(30.27016, abs=1e-5)
    assert first["is_charging_station"] == 0
    assert first["is_virtual_station"] == 0
    # An array of scalars is stored comma-joined rather than dropped.
    assert "creditcard" in first["rental_methods"]


@pytest.mark.parametrize("feed_set", DOCKED)
def test_station_status(gbfs_client, feed_set):
    status = gbfs_client(feed_set).station_status().stations.set_index("station_id")
    assert list(status.index) == ["1", "2", "3"]
    # 2.3's num_bikes_* land on the 3.0 names.
    assert status["num_vehicles_available"].notna().all()
    assert status["num_vehicles_disabled"].notna().all()
    assert status["num_docks_available"].notna().all()
    assert (status["is_renting"] == 1).all()
    assert (status["is_installed"] == 1).all()
    assert status.loc["3", "num_vehicles_available"] == 1


@pytest.mark.parametrize("feed_set", DOCKED)
def test_station_vehicle_types_available(gbfs_client, feed_set):
    """
    The nested per-type array, flattened. This is the only record of which
    vehicles are where, and is where an electric count comes from.
    """
    status = gbfs_client(feed_set).station_status()
    frame = status.vehicle_types_available
    assert len(frame) == 9  # three stations x three types
    assert set(frame["vehicle_type_id"]) == {"FIT", "BOOST", "EFIT"}
    # The breakdown has to add up to the headline count, or the electric split
    # derived from it would not either.
    totals = frame.groupby("station_id")["count"].sum()
    headline = status.stations.set_index("station_id")["num_vehicles_available"]
    assert totals.sort_index().tolist() == headline.sort_index().tolist()


@pytest.mark.parametrize("feed_set", DOCKED)
def test_station_vehicle_docks_available(gbfs_client, feed_set):
    status = gbfs_client(feed_set).station_status()
    frame = status.vehicle_docks_available
    row = frame[frame["station_id"] == "1"].iloc[0]
    # The set of accepted types, sorted so it is stable between snapshots.
    assert row["vehicle_type_ids"] == "BOOST, EFIT, FIT"
    headline = status.stations.set_index("station_id")["num_docks_available"]
    assert row["count"] == headline.loc["1"]


@pytest.mark.parametrize("feed_set", DOCKED)
def test_last_reported_is_epoch_seconds(gbfs_client, feed_set):
    status = gbfs_client(feed_set).station_status().stations
    reported = status["last_reported"].dropna()
    assert len(reported) == 3
    assert reported.map(lambda v: isinstance(v, int)).all()
    assert (reported > 1_700_000_000).all()


@pytest.mark.parametrize("feed_set", DOCKED)
def test_vehicle_types(gbfs_client, feed_set):
    types = gbfs_client(feed_set).vehicle_types().set_index("vehicle_type_id")
    assert set(types.index) == {"ICONIC", "EFIT", "CHLOE"}
    assert types.loc["CHLOE", "form_factor"] == "scooter_standing"
    assert types.loc["EFIT", "propulsion_type"] == "electric_assist"
    assert types.loc["EFIT", "name"] == "EFIT"
    assert types.loc["EFIT", "default_pricing_plan_id"] == "182"
    assert "183" in types.loc["EFIT", "pricing_plan_ids"]


@pytest.mark.parametrize("feed_set", DOCKED)
def test_system_pricing_plans(gbfs_client, feed_set):
    plans = gbfs_client(feed_set).system_pricing_plans().set_index("plan_id")
    assert set(plans.index) == {"182", "183"}
    assert plans.loc["182", "name"] == "Pay-as-you-ride"
    assert plans.loc["182", "currency"] == "USD"
    assert plans.loc["183", "price"] == 10.0
    assert plans.loc["182", "is_taxable"] == 0
    # An array of objects with no flat shape is kept as published.
    assert '"rate":2.5' in plans.loc["182", "per_min_pricing"]


@pytest.mark.parametrize("feed_set", DOCKED)
def test_gbfs_versions(gbfs_client, feed_set):
    versions = gbfs_client(feed_set).gbfs_versions()
    assert "3.0" in set(versions["version"])


@pytest.mark.parametrize("feed_set", DOCKED)
def test_empty_regions_are_not_an_error(gbfs_client, feed_set):
    """Austin publishes system_regions as an empty array, which is valid GBFS."""
    assert gbfs_client(feed_set).system_regions().empty


@pytest.mark.parametrize("feed_set", DOCKED)
def test_unadvertised_feed_reads_empty(gbfs_client, feed_set):
    """Austin publishes no system_alerts at all. Absent is not an error."""
    client = gbfs_client(feed_set)
    assert not client.has_feed("system_alerts")
    assert client.system_alerts().empty
    assert client.vehicle_status().empty


@pytest.mark.parametrize("feed_set", FREE_FLOATING)
def test_a_system_with_no_docks_has_no_station_status(gbfs_client, feed_set):
    status = gbfs_client(feed_set).station_status()
    assert status.stations.empty
    assert status.vehicle_types_available.empty
    assert status.vehicle_docks_available.empty


@pytest.mark.parametrize("feed_set", FREE_FLOATING)
def test_vehicle_status(gbfs_client, feed_set):
    vehicles = gbfs_client(feed_set).vehicle_status().set_index("vehicle_id")
    # 3.0 renamed bike_id to vehicle_id and made the flags real booleans.
    assert list(vehicles.index) == ["2b2f1a30", "9c41dd02", "7fa03b91"]
    assert vehicles.loc["9c41dd02", "is_disabled"] == 1
    assert vehicles.loc["7fa03b91", "is_reserved"] == 1
    assert vehicles.loc["2b2f1a30", "is_reserved"] == 0
    assert vehicles.loc["2b2f1a30", "current_range_meters"] == 12400.0
    assert vehicles.loc["2b2f1a30", "current_fuel_percent"] == pytest.approx(0.62)
    assert vehicles.loc["2b2f1a30", "vehicle_type_id"] == "scooter"
    assert vehicles.loc["2b2f1a30", "home_station_id"] == "h1"
    assert vehicles.loc["2b2f1a30", "pricing_plan_id"] == "182"
    assert vehicles.loc["2b2f1a30", "vehicle_equipment"] == "child_seat_a, helmet"
    assert vehicles.loc["7fa03b91", "station_id"] == "s9"
    assert vehicles.loc["2b2f1a30", "lat"] == pytest.approx(30.27016, abs=1e-5)
    # A classic bike publishes no range; that stays missing, not zero.
    assert pd.isna(vehicles.loc["7fa03b91", "current_range_meters"])
    assert vehicles.loc["2b2f1a30", "last_reported"] == 1793295300


# --- the two specs agree ---------------------------------------------------


def _views(client):
    status = client.station_status()
    return {
        "station_information": (client.station_information(), "station_id"),
        "station_status": (status.stations, "station_id"),
        "station_vehicle_types_available": (
            status.vehicle_types_available, "vehicle_type_id"
        ),
        "station_vehicle_docks_available": (
            status.vehicle_docks_available, "vehicle_type_ids"
        ),
        "vehicle_types": (client.vehicle_types(), "vehicle_type_id"),
        "system_pricing_plans": (client.system_pricing_plans(), "plan_id"),
        "gbfs_versions": (client.gbfs_versions(), "version"),
    }


@pytest.mark.parametrize(
    "view",
    [
        "station_information",
        "station_status",
        "station_vehicle_types_available",
        "station_vehicle_docks_available",
        "vehicle_types",
        "system_pricing_plans",
        "gbfs_versions",
    ],
)
def test_specs_agree(gbfs_client, view):
    """
    The same system on 2.3 and on 3.0 normalizes to the same rows.

    These fixtures are the live Austin feeds recorded seconds apart, so
    last_reported can differ by a tick; nothing else may.
    """
    frames = []
    for feed_set in DOCKED:
        frame, sort_on = _views(gbfs_client(feed_set))[view]
        frame = frame.drop(columns=["last_reported"], errors="ignore")
        frames.append(frame.sort_values(sort_on).reset_index(drop=True))
    pd.testing.assert_frame_equal(frames[0], frames[1], check_dtype=False)


def test_free_floating_specs_agree(gbfs_client):
    frames = [
        gbfs_client(feed_set)
        .vehicle_status()
        .sort_values("vehicle_id")
        .reset_index(drop=True)
        for feed_set in FREE_FLOATING
    ]
    pd.testing.assert_frame_equal(frames[0], frames[1], check_dtype=False)


def test_system_information_specs_agree_where_the_feeds_do(gbfs_client):
    """
    Only on the fields both documents carry.

    Austin's 3.0 system_information genuinely says more than its 2.3 one — it
    adds opening_hours, feed_contact_email and the full languages list, and
    formats the phone number differently. That is the publisher's data
    changing, not the parser's, so this compares the overlap and checks the
    3.0-only fields are read rather than dropped.
    """
    shared = ("system_id", "name", "timezone", "email", "url", "operator")
    records = [
        gbfs_client(feed_set).system_information() for feed_set in DOCKED
    ]
    assert {k: records[0][k] for k in shared} == {k: records[1][k] for k in shared}

    v23, v30 = records
    assert v23["languages"] == "en"
    assert v30["languages"] == "en, fr, nl, es"
    assert v23["opening_hours"] is None
    assert v30["opening_hours"] == "Mo-Su,PH 00:00-24:00"
    assert v30["feed_contact_email"] == "mobility-data-client@lyft.com"
