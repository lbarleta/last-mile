"""
Live Ops metrics on the seeded lake: three stations, one per status.

Kept to the rules NOTES.md states; the KPI arithmetic underneath is due for a
rewrite and is only checked where a wrong answer would be obvious to an operator.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from seed import START, STATUS_COLUMNS, key

from lastmile.metrics import Metrics, coverage
from lastmile.metrics.live_ops import station_status_bucket
from lastmile.settings import ENV_PREFIX, get_settings


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    """A square around the seeded stations, standing in for the city limits."""
    path = tmp_path / "boundary.geojson"
    square = [
        [-97.80, 30.25],
        [-97.70, 30.25],
        [-97.70, 30.31],
        [-97.80, 30.31],
        [-97.80, 30.25],
    ]
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [square]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(f"{ENV_PREFIX}_BOUNDARY_GEOJSON", str(path))
    get_settings.cache_clear()
    coverage._load_boundary.cache_clear()
    return path


def row(bikes: int, docks: int) -> pd.Series:
    return pd.Series({"num_vehicles_available": bikes, "num_docks_available": docks})


# --- station states ----------------------------------------------------------


@pytest.mark.parametrize(
    "bikes, docks, expected",
    [
        (0, 20, "empty"),
        (20, 0, "full"),
        (0, 0, "empty"),  # empty wins when both are zero
        (3, 17, "low"),  # 15% < 20%
        (4, 16, "healthy"),  # exactly 20% is not low
        (10, 10, "healthy"),
    ],
)
def test_station_status_bucket(bikes, docks, expected):
    assert station_status_bucket(row(bikes, docks)) == expected


def test_low_threshold_comes_from_settings(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}_LOW_STATION_BIKE_SHARE", "0.5")
    get_settings.cache_clear()
    assert station_status_bucket(row(4, 16)) == "low"


# --- snapshot KPIs -------------------------------------------------------------


def test_live_ops_counts_the_seeded_stations(seeded, boundary):
    live = Metrics(conn=seeded).get_live_ops_metrics(key(0))
    assert live["timestamp"] == key(0)
    assert live["total_stations"] == 3
    assert (
        live["empty_stations"],
        live["full_stations"],
        live["healthy_stations"],
    ) == (1, 1, 1)
    assert live["total_bikes"] == 30
    assert live["ebikes_available"] == 4  # min(vehicles, 2) for b and c
    assert live["docks_available"] == 30
    # Free-floating bikes join the fleet: three vehicles, one disabled.
    assert live["free_bikes_total"] == 3
    assert live["available_bikes"] == 33
    assert live["disabled_bikes_total"] == 1
    assert live["bikes_per_10_docks"] == pytest.approx(11.0)


def test_first_snapshot_has_no_deltas_or_baseline(seeded, boundary):
    live = Metrics(conn=seeded).get_live_ops_metrics(key(0))
    assert live["prior_timestamp"] is None
    assert live["bikes_per_10_docks_typical"] is None
    assert all(value is None for value in live["deltas"].values())


def test_deltas_compare_against_the_prior_hour(seeded, boundary):
    live = Metrics(conn=seeded).get_live_ops_metrics(key(1))
    assert live["prior_timestamp"] == key(0)
    # The free-floating bikes were only reported in the first hour.
    assert live["deltas"]["available_bikes"] == -3
    assert live["deltas"]["total_stations"] == 0


def test_supply_baseline_uses_the_same_clock_hour(seeded, boundary):
    # key(24) is the same clock hour one day later, and the only earlier sample.
    live = Metrics(conn=seeded).get_live_ops_metrics(key(24))
    assert live["bikes_per_10_docks_samples"] == 1
    # Hour 0 held three free bikes on top of the 30 docked; now it is 30/30.
    assert live["bikes_per_10_docks_typical"] == pytest.approx(11.0)
    assert live["bikes_per_10_docks_vs_typical"] == pytest.approx(-1.0)


def test_empty_lake_returns_the_empty_shape(lake):
    live = Metrics(conn=lake).get_live_ops_metrics()
    assert live["timestamp"] is None
    assert live["total_stations"] == 0
    assert live["stations"].empty


def test_status_by_region_sums_to_the_region_totals(seeded):
    frame = (
        Metrics(conn=seeded).get_station_status_by_region(key(0)).set_index("region")
    )
    assert frame.loc["North", "total"] == 2
    assert frame.loc["North", ["empty", "full"]].tolist() == [1, 1]
    assert frame.loc["South", "healthy"] == 1
    assert frame["pct_healthy"].tolist() == [0.0, 100.0]


def test_problematic_stations_are_the_empty_and_full_ones(seeded):
    frame = Metrics(conn=seeded).get_problematic_stations(key(8))
    assert set(frame["name"]) == {"Alpha", "Bravo"}


# --- coverage ------------------------------------------------------------------


def test_coverage_is_zero_without_bikes(boundary, lake):
    lake.insert_ignore("station_status", STATUS_COLUMNS, [("a", START, 0, 20)])
    result = coverage.compute_coverage(
        pd.DataFrame(columns=["num_vehicles_available", "lat", "lon"])
    )
    assert result["pct_coverage"] == 0.0
    assert result["n_sources"] == 0
    assert result["coverage_geojson"] is None


def test_one_bike_covers_a_small_share_of_the_city(boundary):
    stations = pd.DataFrame(
        [{"num_vehicles_available": 5, "lat": 30.28, "lon": -97.75}]
    )
    result = coverage.compute_coverage(stations, radius_m=300)
    assert 0 < result["pct_coverage"] < 5
    assert result["n_sources"] == 1
    assert result["coverage_geojson"]["geometry"]["type"] == "Polygon"


def test_sources_outside_the_boundary_are_ignored(boundary):
    stations = pd.DataFrame([{"num_vehicles_available": 5, "lat": 31.0, "lon": -98.5}])
    free = pd.DataFrame([{"lat": 30.28, "lon": -97.75, "is_disabled": 1}])
    result = coverage.compute_coverage(stations, free)
    assert result["n_sources"] == 0
