"""Table helpers for Live Ops."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_problematic_stations(df: pd.DataFrame) -> None:
    """Stations empty or full in the recent daytime lookback window."""
    st.subheader("Problematic stations")
    st.caption(
        "Empty or full in the last 3 hours · night hours (9pm–7am) excluded · "
        "backup = nearest non-problematic station within 900 m"
    )
    if df.empty:
        st.info("No problematic stations in this daytime window.")
        return

    display = df.rename(
        columns={
            "name": "Station",
            "region": "Region",
            "hours_problematic": "Hours",
            "issue": "Issue",
            "backup_station": "Backup",
        }
    ).copy()

    def _backup_label(row: pd.Series) -> str:
        name = row.get("Backup")
        if name is None or (isinstance(name, float) and pd.isna(name)) or name == "":
            return "—"
        dist = row.get("backup_distance_m")
        if dist is not None and not (isinstance(dist, float) and pd.isna(dist)):
            return f"{name} ({dist:,.0f} m)"
        return str(name)

    display["Backup"] = display.apply(_backup_label, axis=1)
    display = display[["Station", "Region", "Hours", "Issue", "Backup"]]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        height=455,
    )
