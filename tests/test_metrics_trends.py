"""
Trends metrics on the seeded lake.

The seed is flat on purpose — 30 docked bikes every hour, plus three
free-floating ones in the first hour only — so each rule in NOTES.md shows up
as one recognizable number. Kept lean: the metrics are due for a rewrite.
"""

from __future__ import annotations

import pandas as pd
import pytest
from seed import key

from lastmile.metrics import Metrics

# --- availability --------------------------------------------------------------


def test_free_floating_bikes_stack_onto_the_docked_fleet(seeded):
    ts = (
        Metrics(conn=seeded)
        .get_availability_timeseries(hours=None)
        .set_index("timestamp")
    )
    assert len(ts) == 48
    assert ts.loc[key(0), "free_floating"] == 3
    assert ts.loc[key(1), "free_floating"] == 0
    assert ts.loc[key(0), "total_bikes"] == 33
    assert (
        ts["total_bikes"]
        == ts["classic_available"] + ts["ebikes_available"] + ts["free_floating"]
    ).all()


def test_trailing_hours_window_is_anchored_on_the_last_snapshot(seeded):
    ts = Metrics(conn=seeded).get_availability_timeseries(hours=6)
    assert list(ts["timestamp"]) == [key(h) for h in range(41, 48)]


# --- utilization -----------------------------------------------------------------


def test_fleet_baseline_is_the_overnight_peak(seeded):
    util = Metrics(conn=seeded).get_bike_utilization(hours=None)
    assert util["baseline"] == 30
    assert util["baseline_hour"] == 0
    by_hour = util["by_hour"].set_index("hour")
    # Every hour parks the whole fleet, except hour 6 on the first day, when
    # three free bikes pushed the count above the baseline; the first day has
    # no overnight snapshot, so it borrows the typical fleet size.
    assert by_hour.loc[3, "bikes_in_use"] == 0
    assert by_hour.loc[6, "bikes_in_use"] == -1.5
    assert by_hour.loc[6, "samples"] == 2


def test_without_an_overnight_window_the_peak_on_record_stands_in(seeded):
    daytime = pd.DataFrame(
        {
            "timestamp": [key(h) for h in range(4, 8)],  # 10:00 to 13:00
            "classic_available": [26, 26, 26, 26],
            "ebikes_available": [4, 4, 4, 4],
            "free_floating": [3, 0, 0, 0],
            "total_bikes": [33, 30, 30, 30],
        }
    )
    util = Metrics(conn=seeded).get_bike_utilization(timeseries=daytime)
    assert util["baseline"] == 33
    assert util["baseline_hour"] is None
    assert util["by_hour"].set_index("hour").loc[11, "bikes_in_use"] == 3


def test_utilization_of_an_empty_lake(lake):
    util = Metrics(conn=lake).get_bike_utilization()
    assert util["baseline"] is None
    assert util["by_hour"].empty


# --- problematic stations and reliability ------------------------------------------


def test_problematic_rate_is_zero_overnight_by_construction(seeded):
    by_hour = Metrics(conn=seeded).get_problematic_by_hour(hours=None).set_index("hour")
    # One of three stations is empty and one full all day long.
    assert by_hour.loc[10, "pct_empty"] == pytest.approx(100 / 3)
    assert by_hour.loc[10, "pct_full"] == pytest.approx(100 / 3)
    assert by_hour.loc[3, ["pct_empty", "pct_full"]].tolist() == [0, 0]


def test_reliability_drops_stations_with_too_few_hours(seeded):
    metrics = Metrics(conn=seeded)
    rel = metrics.get_station_reliability(hours=None, min_hours=48).set_index("name")
    assert rel.loc["Alpha", "pct_empty"] == 100
    assert rel.loc["Bravo", "pct_full"] == 100
    assert rel.loc["Delta", ["pct_empty", "pct_full"]].tolist() == [0, 0]
    assert metrics.get_station_reliability(hours=None, min_hours=49).empty
