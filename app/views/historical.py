"""Historical analytics from hourly station_status snapshots."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from components.charts import (
    render_availability_over_time,
    render_daily_pattern,
    render_hourly_pattern,
    render_utilization_hist,
)
from LastMile import LastMileMetrics


def render(metrics_svc: LastMileMetrics) -> None:
    range_options = {
        "Last 24 hours": 24,
        "Last 7 days": 24 * 7,
        "Last 28 days": 24 * 28,
        "All available": None,
    }

    choice = st.selectbox("Time range", list(range_options.keys()), index=1)
    hours = range_options[choice]

    with st.spinner("Aggregating snapshots…"):
        try:
            timeseries = metrics_svc.get_availability_timeseries(hours=hours)
            hourly = metrics_svc.get_hourly_patterns(
                hours=hours if hours is not None else 24 * 7
            )
            daily = metrics_svc.get_daily_patterns(
                hours=hours if hours is not None else 24 * 28
            )
            utilization = metrics_svc.get_utilization_distribution()
        except Exception as exc:
            st.error(f"Failed to load historical metrics: {exc}")
            return

    if timeseries.empty:
        st.warning("No historical data in this range.")
        return

    st.markdown(
        f"**{len(timeseries):,}** hourly snapshots · "
        f"`{timeseries['timestamp'].iloc[0]}` → `{timeseries['timestamp'].iloc[-1]}`"
    )

    st.subheader("Availability over time")
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
                x=alt.X("datetime:T", title="Time"),
                y=alt.Y("count:Q", title="Stations"),
                color="metric:N",
                tooltip=["datetime:T", "metric:N", "count:Q"],
            )
            .properties(height=260)
            .interactive()
        )
        st.altair_chart(chart, width="stretch")
