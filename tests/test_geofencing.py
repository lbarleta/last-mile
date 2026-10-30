"""
Geofencing: whole captures archived as standalone GeoJSON documents.

Zones carry no ids in GBFS and nothing reads them live, so they are not a
table: each version of the collection is one ``.geojson`` file in the lake,
the newest file is current, and a refresh writes a new file only when the
feed's content differs. Geometry is stored exactly as published.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from lastmile import collect, geofencing

FREE_FLOATING = ("freefloat_v23", "freefloat_v30")
FIRST = datetime(2026, 10, 29, 8, 0, 0)
SECOND = datetime(2026, 10, 30, 8, 0, 0)


def zones_of(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- the client passes the payload through ----------------------------------


@pytest.mark.parametrize("feed_set", FREE_FLOATING)
def test_payload_is_passed_through_verbatim(gbfs_client, feed_set):
    data = gbfs_client(feed_set).geofencing_zones()
    features = data["geofencing_zones"]["features"]
    assert len(features) == 2
    # No normalization at all: localized arrays, rule dialects and coordinates
    # arrive exactly as the publisher wrote them.
    geometry = features[0]["geometry"]
    assert geometry["coordinates"][0][0][0] == [-97.741, 30.272]


def test_absent_feed_reads_as_none(gbfs_client, monkeypatch):
    client = gbfs_client("freefloat_v30")
    monkeypatch.setattr(client, "has_feed", lambda name: False)
    assert client.geofencing_zones() is None


# --- the stored document -----------------------------------------------------


def test_each_capture_is_a_valid_geojson_file(lake, gbfs_client):
    collect.refresh_geofencing(lake, gbfs_client("freefloat_v30"), FIRST)
    stored = geofencing.captures(lake.root)
    assert [path.name for path in stored] == ["20261029T080000.geojson"]
    doc = zones_of(stored[0])
    assert doc["type"] == "FeatureCollection"
    assert len(doc["features"]) == 2
    assert geofencing.observed_at(stored[0]) == FIRST


def test_global_rules_ride_as_a_foreign_member(lake, gbfs_client):
    """GBFS 3.0 global_rules sit outside every zone; GeoJSON allows the extra key."""
    collect.refresh_geofencing(lake, gbfs_client("freefloat_v30"), FIRST)
    doc = zones_of(geofencing.latest(lake.root))
    assert doc["global_rules"][0]["ride_through_allowed"] is True


def test_rules_keep_their_spec_dialect(lake, gbfs_client):
    """
    Deliberately not translated: 2.3's single ride_allowed and 3.0's
    start/end split do not map losslessly, and an archive should record what
    the publisher said, not a paraphrase.
    """
    collect.refresh_geofencing(lake, gbfs_client("freefloat_v23"), FIRST)
    rules = zones_of(geofencing.latest(lake.root))["features"][0]["properties"]["rules"]
    assert "ride_allowed" in rules[0]


# --- versioning --------------------------------------------------------------


def test_an_unchanged_feed_writes_no_new_capture(lake, gbfs_client):
    client = gbfs_client("freefloat_v30")
    first = collect.refresh_geofencing(lake, client, FIRST)
    again = collect.refresh_geofencing(lake, client, SECOND)
    assert first["captured"] and not again["captured"]
    assert again == {
        "captures": 1,
        "features": 2,
        "observed_at": FIRST,
        "captured": False,
    }
    assert len(geofencing.captures(lake.root)) == 1


def test_reordered_features_are_not_a_new_version(lake, gbfs_client, monkeypatch):
    client = gbfs_client("freefloat_v30")
    collect.refresh_geofencing(lake, client, FIRST)
    data = client.geofencing_zones()
    data["geofencing_zones"]["features"].reverse()
    monkeypatch.setattr(client, "geofencing_zones", lambda: data)
    result = collect.refresh_geofencing(lake, client, SECOND)
    assert not result["captured"]


def test_a_changed_collection_becomes_a_new_capture(lake, gbfs_client, monkeypatch):
    client = gbfs_client("freefloat_v30")
    collect.refresh_geofencing(lake, client, FIRST)

    data = client.geofencing_zones()
    rules = data["geofencing_zones"]["features"][0]["properties"]["rules"]
    rules[0]["maximum_speed_kph"] = 10
    monkeypatch.setattr(client, "geofencing_zones", lambda: data)
    result = collect.refresh_geofencing(lake, client, SECOND)

    assert result["captured"] and result["captures"] == 2
    old, new = geofencing.captures(lake.root)
    # The superseded capture is untouched on disk; the newest file is current.
    assert geofencing.observed_at(old) == FIRST
    assert geofencing.observed_at(new) == SECOND
    speeds = {
        path.name: zones_of(path)["features"][0]["properties"]["rules"][0][
            "maximum_speed_kph"
        ]
        for path in (old, new)
    }
    assert speeds == {old.name: 15, new.name: 10}


def test_an_emptied_collection_is_a_real_version(lake, gbfs_client, monkeypatch):
    """A system that deleted all its zones has none; record that it did."""
    client = gbfs_client("freefloat_v30")
    collect.refresh_geofencing(lake, client, FIRST)
    monkeypatch.setattr(
        client,
        "geofencing_zones",
        lambda: {"geofencing_zones": {"type": "FeatureCollection", "features": []}},
    )
    result = collect.refresh_geofencing(lake, client, SECOND)
    assert result["captured"]
    assert result["features"] == 0
    assert len(geofencing.captures(lake.root)) == 2


def test_an_absent_feed_is_a_no_op(lake, gbfs_client, monkeypatch):
    client = gbfs_client("freefloat_v30")
    collect.refresh_geofencing(lake, client, FIRST)
    monkeypatch.setattr(client, "has_feed", lambda name: False)
    result = collect.refresh_geofencing(lake, client, SECOND)
    assert not result["captured"]
    assert result["captures"] == 1


def test_an_empty_feed_is_one_capture_that_never_multiplies(lake, gbfs_client):
    """
    Austin advertises the feed and publishes zero features; most docked
    systems do. The empty capture is stored — it is what distinguishes "this
    system had no zones" from "nobody looked" — and stays one file for as long
    as the feed stays empty, because unchanged content is never rewritten.
    """
    result = collect.refresh_geofencing(lake, gbfs_client("v30"), FIRST)
    assert result == {
        "captures": 1,
        "features": 0,
        "observed_at": FIRST,
        "captured": True,
    }
    again = collect.refresh_geofencing(lake, gbfs_client("v30"), SECOND)
    assert again["captures"] == 1
    assert not again["captured"]
    doc = zones_of(geofencing.latest(lake.root))
    assert doc["type"] == "FeatureCollection"
    assert doc["features"] == []


def test_refresh_reference_data_includes_geofencing(lake, gbfs_client):
    results = collect.init_db(lake, gbfs_client("freefloat_v30"))
    assert results["geofencing_zones"]["features"] == 2
    assert results["geofencing_zones"]["captured"]
