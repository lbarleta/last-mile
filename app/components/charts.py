"""Altair chart helpers for historical views."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st


def render_availability_over_time(ts: pd.DataFrame) -> None:
    if ts.empty:
        st.info("No historical snapshots in this range.")
        return

    df = ts.melt(
        id_vars=["timestamp"],
        value_vars=["bikes_available", "ebikes_available", "docks_available"],
        var_name="metric",
        value_name="count",
    )
    label_map = {
        "bikes_available": "Bikes",
        "ebikes_available": "E-bikes",
        "docks_available": "Docks",
    }
    df["metric"] = df["metric"].map(label_map)
    df["datetime"] = pd.to_datetime(df["timestamp"], format="%Y-%m-%d-%H:00")

    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=alt.X("datetime:T", title="Time"),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("metric:N", title=""),
            tooltip=["datetime:T", "metric:N", "count:Q"],
        )
        .properties(height=320)
        .interactive()
    )
    st.altair_chart(chart, width="stretch")


def render_hourly_pattern(hourly: pd.DataFrame) -> None:
    if hourly.empty:
        st.info("Not enough data for hourly patterns.")
        return

    chart = (
        alt.Chart(hourly)
        .mark_bar()
        .encode(
            x=alt.X("hour:O", title="Hour of day"),
            y=alt.Y("avg_bikes:Q", title="Avg bikes available"),
            tooltip=[
                alt.Tooltip("hour:O", title="Hour"),
                alt.Tooltip("avg_bikes:Q", title="Avg bikes", format=".0f"),
                alt.Tooltip("avg_empty:Q", title="Avg empty stations", format=".1f"),
                alt.Tooltip("samples:Q", title="Samples"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")


def render_daily_pattern(daily: pd.DataFrame) -> None:
    if daily.empty:
        st.info("Not enough data for day-of-week patterns.")
        return

    chart = (
        alt.Chart(daily)
        .mark_bar()
        .encode(
            x=alt.X("day_of_week:N", title="Day", sort=list(daily["day_of_week"])),
            y=alt.Y("avg_bikes:Q", title="Avg bikes available"),
            tooltip=[
                "day_of_week:N",
                alt.Tooltip("avg_bikes:Q", title="Avg bikes", format=".0f"),
                alt.Tooltip("avg_empty:Q", title="Avg empty stations", format=".1f"),
                alt.Tooltip("samples:Q", title="Samples"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")


def render_utilization_hist(util: pd.DataFrame) -> None:
    if util.empty or "utilization" not in util.columns:
        st.info("No utilization data available.")
        return

    df = util.dropna(subset=["utilization"]).copy()
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("utilization:Q", bin=alt.Bin(maxbins=20), title="Utilization (bikes / bikes+docks)"),
            y=alt.Y("count()", title="Stations"),
            tooltip=[alt.Tooltip("count()", title="Stations")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")


def render_region_status_pct(by_region: pd.DataFrame) -> None:
    """Vertical grouped bar chart of station status mix (%) by region."""
    if by_region.empty:
        st.info("No regional station data in this snapshot.")
        return

    statuses = ["Empty", "Low", "Healthy", "Full"]
    value_vars = ["pct_empty", "pct_low", "pct_healthy", "pct_full"]
    count_cols = ["empty", "low", "healthy", "full"]

    df = by_region.melt(
        id_vars=["region", "total", *count_cols],
        value_vars=value_vars,
        var_name="metric",
        value_name="pct",
    )
    df["status"] = df["metric"].map(
        {
            "pct_empty": "Empty",
            "pct_low": "Low",
            "pct_healthy": "Healthy",
            "pct_full": "Full",
        }
    )
    region_order = by_region["region"].tolist()

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("region:N", title=None, sort=region_order),
            y=alt.Y(
                "pct:Q",
                title="% of stations in region",
                scale=alt.Scale(domain=[0, 100]),
            ),
            color=alt.Color(
                "status:N",
                title=None,
                scale=alt.Scale(
                    domain=statuses,
                    range=["#b42828", "#dc8c28", "#288c5a", "#285ab4"],
                ),
                sort=statuses,
            ),
            xOffset=alt.XOffset("status:N", sort=statuses),
            tooltip=[
                alt.Tooltip("region:N", title="Region"),
                alt.Tooltip("status:N", title="Status"),
                alt.Tooltip("pct:Q", title="% of region", format=".1f"),
                alt.Tooltip("empty:Q", title="Empty"),
                alt.Tooltip("low:Q", title="Low"),
                alt.Tooltip("healthy:Q", title="Healthy"),
                alt.Tooltip("full:Q", title="Full"),
                alt.Tooltip("total:Q", title="Stations in region"),
            ],
        )
        .properties(height=340, title="Station availability by region")
    )
    st.altair_chart(chart, width="stretch")
