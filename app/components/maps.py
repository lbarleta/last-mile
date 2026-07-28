"""Map helpers for station availability."""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st


STATUS_COLORS = {
    "empty": [180, 40, 40],
    "low": [220, 140, 40],
    "healthy": [40, 140, 90],
    "full": [40, 90, 180],
}


def availability_bucket(row: pd.Series) -> str:
    if row["num_bikes_available"] == 0:
        return "empty"
    if row["num_docks_available"] == 0:
        return "full"
    capacity = row["num_bikes_available"] + row["num_docks_available"]
    if capacity > 0 and row["num_bikes_available"] / capacity < 0.2:
        return "low"
    return "healthy"


def render_station_map(stations: pd.DataFrame) -> None:
    if stations.empty:
        st.info("No station data to map.")
        return

    df = stations.copy()
    df["status"] = df.apply(availability_bucket, axis=1)
    df["color"] = df["status"].map(STATUS_COLORS)
    df["radius"] = 60 + df["num_bikes_available"].clip(upper=30) * 4

    mid_lat = float(df["lat"].mean())
    mid_lon = float(df["lon"].mean())

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius="radius",
        pickable=True,
        opacity=0.85,
    )
    view = pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=11, pitch=0)
    tooltip = {
        "html": (
            "<b>{name}</b><br/>"
            "{region}<br/>"
            "Bikes: {num_bikes_available} · Docks: {num_docks_available}<br/>"
            "E-bikes: {num_ebikes_available} · Status: {status}"
        ),
        "style": {"backgroundColor": "#1a1a1a", "color": "white"},
    }
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=tooltip))

    legend = " · ".join(
        [
            "Empty (red)",
            "Low (amber)",
            "Healthy (green)",
            "Full (blue)",
        ]
    )
    st.caption(legend)
