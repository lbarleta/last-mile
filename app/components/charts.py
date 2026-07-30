"""Altair chart helpers for historical views."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st


BIKE_SERIES = ["Docked classic", "Docked e-bikes", "Free-floating"]
SERIES_COLORS = {
    "Docked classic": "#285ab4",
    "Docked e-bikes": "#1f6f54",
    "Free-floating": "#783cc0",
    "Available docks": "#7a828a",
}
DOCK_DASH = [5, 3]

# Hour steps the time axis may tick at, coarsest label density last.
_TICK_STEPS_H = (1, 2, 3, 6, 12, 24, 48, 72, 168, 336, 720)
_MAX_TICKS = 15


def time_axis(datetimes: pd.Series, label_padding: int = 6) -> alt.Axis:
    """
    Two-line time axis: clock time on top, calendar day underneath.

    Ticks are chosen here rather than by Vega so the leftmost one always lands
    on the first observation. The date is printed only on the first tick of
    each day, which keeps a day from repeating across every tick.
    """
    values = pd.to_datetime(pd.Series(datetimes)).dropna().sort_values()
    if values.empty:
        return alt.Axis(labelPadding=label_padding)

    first, last = values.iloc[0], values.iloc[-1]
    span_hours = max((last - first).total_seconds() / 3600.0, 1.0)
    step = next(
        (s for s in _TICK_STEPS_H if span_hours / s <= _MAX_TICKS), _TICK_STEPS_H[-1]
    )

    freq = f"{step}h"
    ticks = [first]
    # Subsequent ticks sit on round boundaries; drop one crowding the first.
    for tick in pd.date_range(first.ceil(freq), last, freq=freq):
        if tick - ticks[-1] >= pd.Timedelta(hours=step) / 2:
            ticks.append(tick)

    first_key = first.strftime("%Y-%m-%d %H")
    label_expr = (
        "[timeFormat(datum.value, '%-I %p'), "
        "(hours(datum.value) == 0 || "
        f"timeFormat(datum.value, '%Y-%m-%d %H') == '{first_key}') "
        "? timeFormat(datum.value, '%b %-d') : '']"
    )
    return alt.Axis(
        values=[tick.to_pydatetime() for tick in ticks],
        labelExpr=label_expr,
        labelPadding=label_padding,
    )


def render_availability_over_time(ts: pd.DataFrame) -> None:
    """Rideable fleet split by type, with dock supply as a separate line."""
    if ts.empty:
        st.info("No historical snapshots in this range.")
        return

    label_map = {
        "classic_available": "Docked classic",
        "ebikes_available": "Docked e-bikes",
        "free_floating": "Free-floating",
    }
    available = [col for col in label_map if col in ts.columns]

    wide = ts.copy()
    wide["datetime"] = pd.to_datetime(wide["timestamp"], format="%Y-%m-%d-%H:00")
    if "total_bikes" not in wide.columns:
        wide["total_bikes"] = sum(wide[c] for c in available)
    tip_cols = [
        "datetime",
        "total_bikes",
        "docks_available",
        "classic_available",
        "ebikes_available",
        "free_floating",
    ]

    bikes = wide.melt(
        id_vars=["timestamp", "datetime"],
        value_vars=available,
        var_name="metric",
        value_name="count",
    )
    bikes["series"] = bikes["metric"].map(label_map)
    bikes = bikes.merge(wide[tip_cols], on="datetime", how="left")

    docks = wide[tip_cols].copy()
    docks["count"] = docks["docks_available"]
    docks["series"] = "Available docks"

    stacked = [s for s in BIKE_SERIES if s in set(bikes["series"])]
    x = alt.X("datetime:T", title=None, axis=time_axis(bikes["datetime"]))
    y = alt.Y("count:Q", title=None, stack="zero", scale=alt.Scale(nice=True))
    tooltip = [
        alt.Tooltip("datetime:T", title="Hour", format="%b %-d, %-I %p"),
        alt.Tooltip("total_bikes:Q", title="Total bikes", format=","),
        alt.Tooltip("docks_available:Q", title="Total docks", format=","),
        alt.Tooltip("classic_available:Q", title="Docked classic", format=","),
        alt.Tooltip("ebikes_available:Q", title="Docked e-bikes", format=","),
        alt.Tooltip("free_floating:Q", title="Free-floating", format=","),
    ]

    bike_area = (
        alt.Chart(bikes)
        .mark_area(line={"strokeWidth": 1}, opacity=0.85)
        .encode(
            x=x,
            y=y,
            color=alt.Color(
                "series:N",
                title=None,
                scale=alt.Scale(
                    domain=stacked, range=[SERIES_COLORS[s] for s in stacked]
                ),
                sort=stacked,
                legend=alt.Legend(
                    orient="bottom", direction="horizontal", symbolType="square"
                ),
            ),
            order=alt.Order("series:N", sort="descending"),
            tooltip=tooltip,
        )
    )
    # Docks use an independent colour scale so the legend can be a stroke
    # symbol with the same dash pattern as the line (strokeDash encoding
    # alone often draws a solid legend mark in Streamlit's Vega renderer).
    dock_line = (
        alt.Chart(docks)
        .mark_line(strokeWidth=2, strokeDash=DOCK_DASH)
        .encode(
            x=x,
            y=y,
            color=alt.Color(
                "series:N",
                title=None,
                scale=alt.Scale(
                    domain=["Available docks"],
                    range=[SERIES_COLORS["Available docks"]],
                ),
                legend=alt.Legend(
                    orient="bottom",
                    direction="horizontal",
                    symbolType="stroke",
                    symbolStrokeWidth=2,
                    symbolDash=DOCK_DASH,
                ),
            ),
            tooltip=tooltip,
        )
    )

    chart = (
        (bike_area + dock_line)
        .resolve_scale(color="independent")
        .properties(height=340, padding={"left": 4, "right": 12, "top": 4, "bottom": 8})
        .configure_view(strokeWidth=0)
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
