"""Historical analytics from hourly station_status snapshots."""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from components import format_snapshot_datetime
from components.charts import (
    hour_text,
    render_availability_over_time,
    render_bikes_out_by_day,
    render_bikes_out_by_hour,
    render_utilization_hist,
    time_axis,
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


def _bikes_out_blurb() -> str:
    return (
        "This is an estimate, since the GBFS feed doesn't report fleet size or "
        "which bikes are being ridden, serviced, or moved by van. We assume a "
        "closed fleet, using the highest count seen overnight (midnight–4am) as "
        "the baseline. Bikes in use = baseline minus bikes currently available. "
        "We re-estimate this baseline daily so fleet growth doesn't get mistaken "
        "for demand."
    )


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
            # Deliberately unfiltered: the estimate infers bikes away from a
            # fleet baseline, which only holds for a pool bikes cannot leave.
            # A single region trades bikes with its neighbours.
            systemwide = (
                timeseries
                if region is None
                else _load_timeseries(metrics_svc, hours, None, latest)
            )
            bikes_out = metrics_svc.get_bikes_out_patterns(timeseries=systemwide)
            utilization = metrics_svc.get_utilization_distribution(region=region)
        except Exception as exc:
            st.error(f"Failed to load historical metrics: {exc}")
            return

    if timeseries.empty:
        st.warning("No historical data in this range.")
        return

    scope = "" if region is None else f" · {region}"
    st.markdown(
        f"**{len(timeseries):,}** hourly snapshots · "
        f"{format_snapshot_datetime(timeseries['timestamp'].iloc[0])} → "
        f"{format_snapshot_datetime(timeseries['timestamp'].iloc[-1])}{scope}"
    )

    st.subheader("Bike and Dock Availability")
    render_availability_over_time(timeseries)

    st.subheader("Bike Utilization (system-wide)")
    st.caption(_bikes_out_blurb())

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Peak hours")
        st.caption("Average bikes in use by hour of day")
        render_bikes_out_by_hour(bikes_out["by_hour"])
    with c2:
        st.markdown("##### Peak days")
        st.caption("Average bikes in use by day of week")
        render_bikes_out_by_day(bikes_out["by_day"])

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
        empty_full["hour_label"] = hour_text(empty_full["datetime"])
        empty_full["metric"] = empty_full["metric"].map(
            {"empty_stations": "Empty", "full_stations": "Full"}
        )
        chart = (
            alt.Chart(empty_full)
            .mark_line()
            .encode(
                x=alt.X(
                    "datetime:T", title=None, axis=time_axis(empty_full["datetime"])
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
                    alt.Tooltip("hour_label:N", title="Hour"),
                    alt.Tooltip("metric:N", title="Status"),
                    alt.Tooltip("count:Q", title="Stations"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, width="stretch")
