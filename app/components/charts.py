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
    """Horizontal grouped bar chart of station status mix (%) by region."""
    if by_region.empty:
        st.info("No regional station data in this snapshot.")
        return

    st.markdown(
        """
        <style>
          div[data-testid="stElementContainer"]:has(.lm-region-head) {
            margin-bottom: 1.15rem !important;
          }
          .lm-region-head { margin: 0; }
          .lm-region-title {
            font-size: 1.05rem;
            font-weight: 600;
            color: #1c1f24;
            line-height: 1.3;
            margin: 0;
          }
          .lm-region-caption {
            font-size: 0.85rem;
            color: #7a828a;
            margin: 0.15rem 0 0 0;
            line-height: 1.3;
          }
        </style>
        <div class="lm-region-head">
          <div class="lm-region-title">Station status by region</div>
          <div class="lm-region-caption">Share of stations in each status for the selected snapshot</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
    x_max = float(df["pct"].max()) if not df.empty else 0.0
    x_max = min(100.0, max(20.0, (x_max * 1.12 + 2)))

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            y=alt.Y(
                "region:N",
                title=None,
                sort=region_order,
                scale=alt.Scale(paddingInner=0.15, paddingOuter=0.05),
            ),
            x=alt.X(
                "pct:Q",
                title="% of stations in region",
                scale=alt.Scale(domain=[0, x_max], nice=False),
                axis=alt.Axis(
                    tickCount=5,
                    titlePadding=4,
                    titleAnchor="start",
                    titleAlign="left",
                ),
            ),
            color=alt.Color(
                "status:N",
                title=None,
                scale=alt.Scale(
                    domain=statuses,
                    range=["#b42828", "#dc8c28", "#288c5a", "#285ab4"],
                ),
                sort=statuses,
                legend=alt.Legend(
                    orient="top-right",
                    direction="vertical",
                    title=None,
                    offset=0,
                    padding=0,
                    columnPadding=8,
                    labelOffset=2,
                    labelSeparation=4,
                ),
            ),
            yOffset=alt.YOffset("status:N", sort=statuses),
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
        .properties(
            height=max(420, len(region_order) * 78),
            padding={"left": 4, "right": 12, "top": 4, "bottom": 28},
        )
        .configure_view(strokeWidth=0)
        .configure_axis(labelPadding=2, titlePadding=2)
        .configure_legend(symbolType="square")
    )
    st.altair_chart(chart, width="stretch")
