"""Historical analytics from hourly station_status snapshots."""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from components import format_snapshot_datetime
from components.charts import (
    TIME_AXIS_LABEL_EXPR,
    render_availability_over_time,
    render_daily_pattern,
    render_hourly_pattern,
    render_utilization_hist,
)
from LastMile import LastMileMetrics

ALL_REGIONS = "All regions"

RANGE_OPTIONS = {
    "Last 24 hours": 24,
    "Last 7 days": 24 * 7,
    "Last 28 days": 24 * 28,
    "All available": None,
}


@st.cache_data(show_spinner=False)
def _load_timeseries(
    _metrics_svc: LastMileMetrics,
    hours: Optional[int],
    region: Optional[str],
    latest: Optional[str],
) -> pd.DataFrame:
    """
    Availability series for the selected range and region.

    ``latest`` is not used directly — it is part of the cache key so a newly
    collected snapshot invalidates the cached frame.
    """
    return _metrics_svc.get_availability_timeseries(hours=hours, region=region)


def render(metrics_svc: LastMileMetrics) -> None:
    left, right = st.columns([2, 2])
    with left:
        choice = st.selectbox("Time range", list(RANGE_OPTIONS.keys()), index=1)
    with right:
        try:
            regions = metrics_svc.list_regions()
        except Exception:
            regions = []
        region_choice = st.selectbox("Region", [ALL_REGIONS, *regions], index=0)

    hours = RANGE_OPTIONS[choice]
    region = None if region_choice == ALL_REGIONS else region_choice

    with st.spinner("Aggregating snapshots…"):
        try:
            latest = metrics_svc.get_latest_timestamp()
            timeseries = _load_timeseries(metrics_svc, hours, region, latest)
            hourly = metrics_svc.get_hourly_patterns(timeseries=timeseries)
            daily = metrics_svc.get_daily_patterns(timeseries=timeseries)
            utilization = metrics_svc.get_utilization_distribution(region=region)
        except Exception as exc:
            st.error(f"Failed to load historical metrics: {exc}")
            return

    if timeseries.empty:
        st.warning("No historical data in this range.")
        return

    scope = "all regions" if region is None else region
    st.markdown(
        f"**{len(timeseries):,}** hourly snapshots · "
        f"{format_snapshot_datetime(timeseries['timestamp'].iloc[0])} → "
        f"{format_snapshot_datetime(timeseries['timestamp'].iloc[-1])} · {scope}"
    )

    st.subheader("Availability over time")
    st.caption(
        "Rideable bikes stack into the total fleet; available docks are the "
        "capacity to return one. GBFS counts e-bikes inside the docked bike "
        "total, so classic is shown net of them."
    )
    render_availability_over_time(timeseries)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Peak hours")
        st.caption("Average bikes available by hour of day")
        render_hourly_pattern(hourly)
    with c2:
        st.subheader("Day of week")
        st.caption("Average bikes available by weekday")
        render_daily_pattern(daily)

    st.subheader("Station utilization (latest snapshot)")
    st.caption("Share of occupied capacity: bikes / (bikes + docks)")
    render_utilization_hist(utilization)

    with st.expander("Empty / full stations over time"):
        empty_full = timeseries[["timestamp", "empty_stations", "full_stations"]].melt(
            id_vars=["timestamp"],
            var_name="metric",
            value_name="count",
        )
        empty_full["datetime"] = pd.to_datetime(
            empty_full["timestamp"], format="%Y-%m-%d-%H:00"
        )
        empty_full["metric"] = empty_full["metric"].map(
            {"empty_stations": "Empty", "full_stations": "Full"}
        )
        chart = (
            alt.Chart(empty_full)
            .mark_line()
            .encode(
                x=alt.X(
                    "datetime:T",
                    title=None,
                    axis=alt.Axis(labelExpr=TIME_AXIS_LABEL_EXPR, labelPadding=6),
                ),
                y=alt.Y("count:Q", title="Stations"),
                color=alt.Color(
                    "metric:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["Empty", "Full"], range=["#b42828", "#285ab4"]
                    ),
                ),
                tooltip=[
                    alt.Tooltip("datetime:T", title="Hour", format="%b %-d, %-I %p"),
                    alt.Tooltip("metric:N", title="Status"),
                    alt.Tooltip("count:Q", title="Stations"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, width="stretch")
