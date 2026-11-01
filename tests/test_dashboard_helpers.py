"""
The dashboard's pure helpers: functions that take a value and return a string,
series or axis. Nothing here renders; Streamlit is imported but never called.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from lastmile.dashboard.components import (
    format_hour,
    format_snapshot_date,
    format_snapshot_datetime,
    kpis,
)
from lastmile.dashboard.components.charts import hour_text, time_axis
from lastmile.dashboard.components.snapshot_picker import _clamp_day

# --- snapshot labels -------------------------------------------------------------


def test_snapshot_date_and_datetime_labels():
    assert format_snapshot_date("2026-10-28-15:00") == "October 28, 2026"
    assert format_snapshot_datetime("2026-10-28-15:00") == "October 28, 2026 at 3 pm"
    assert format_snapshot_datetime("2026-10-28-00:00") == "October 28, 2026 at 12 am"


def test_malformed_timestamps_fall_back_instead_of_raising():
    assert format_snapshot_date("2026-10-28T15") == "2026-10-28"
    assert format_snapshot_datetime("garbage") == "garbage"


@pytest.mark.parametrize(
    "hour, label",
    [(0, "12 am"), (7, "7 am"), (12, "12 pm"), (15, "3 pm"), (23, "11 pm")],
)
def test_format_hour(hour, label):
    assert format_hour(hour) == label


def test_hour_text_lowercases_the_meridiem():
    series = pd.to_datetime(pd.Series(["2026-07-28 15:00", "2026-07-28 09:00"]))
    assert hour_text(series).tolist() == ["Jul 28, 3 pm", "Jul 28, 9 am"]


# --- KPI formatting ----------------------------------------------------------------


def test_delta_that_rounds_to_zero_reads_as_flat():
    assert "kpi-delta-flat" in kpis._fmt_delta(0.004)
    assert "kpi-delta-flat" in kpis._fmt_delta(0.04, as_pp=True)
    assert "kpi-delta-flat" in kpis._fmt_delta(0.4, as_count=True)
    assert "n/a" in kpis._fmt_delta(None)


def test_delta_direction_and_units():
    assert "▲ 1.50" in kpis._fmt_delta(1.5)
    assert "▼ 2.0 pp" in kpis._fmt_delta(-2.0, as_pp=True)
    assert "▲ 1,200" in kpis._fmt_delta(1200, as_count=True)
    assert "▼ 35 m" in kpis._fmt_delta(-35.4, as_meters=True)
    assert "kpi-delta-down" in kpis._fmt_delta(-1)


def test_distance_switches_to_km_at_a_thousand_meters():
    assert kpis._fmt_distance_m(None) == "n/a"
    assert kpis._fmt_distance_m(999.6) == "1000 m"
    assert kpis._fmt_distance_m(1000) == "1.00 km"
    assert kpis._fmt_distance_m(1234) == "1.23 km"


def test_vs_typical_phrasing():
    assert (
        kpis._fmt_vs_typical(None, "2026-10-28-15:00", 0)
        == "no baseline for this hour yet"
    )
    assert kpis._fmt_vs_typical(0.02, "2026-10-28-15:00", 5) == "typical for 3 pm"
    assert (
        kpis._fmt_vs_typical(1.25, "2026-10-28-15:00", 5)
        == "1.2 above typical for 3 pm"
    )
    assert kpis._fmt_vs_typical(-0.5, None, 5) == "0.5 below typical for this hour"


# --- time axis ------------------------------------------------------------------------


def test_time_axis_first_tick_is_the_first_observation():
    times = pd.to_datetime(
        pd.Series(["2026-10-28 07:00", "2026-10-28 08:00", "2026-10-29 06:00"])
    )
    values = time_axis(times).values
    assert values[0] == times.iloc[0].to_pydatetime()
    assert all(a < b for a, b in zip(values, values[1:]))


def test_time_axis_coarsens_ticks_for_longer_spans():
    day = time_axis(pd.date_range("2026-10-28", periods=24, freq="h").to_series())
    month = time_axis(
        pd.date_range("2026-10-01", periods=24 * 28, freq="h").to_series()
    )
    assert len(day.values) <= 15
    assert len(month.values) <= 15
    assert len(month.values) < len(day.values) * 2


def test_time_axis_of_nothing_has_no_tick_values():
    assert "values" not in time_axis(pd.Series([], dtype="datetime64[ns]")).to_dict()


# --- snapshot picker ------------------------------------------------------------------


def test_clamp_day():
    lo, hi = date(2026, 10, 1), date(2026, 10, 31)
    assert _clamp_day(date(2026, 9, 1), lo, hi) == lo
    assert _clamp_day(date(2026, 11, 1), lo, hi) == hi
    assert _clamp_day(date(2026, 10, 15), lo, hi) == date(2026, 10, 15)
