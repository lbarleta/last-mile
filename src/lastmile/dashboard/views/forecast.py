"""Station stockout forecast: where the system is heading in the next 6 hours."""

from __future__ import annotations

import streamlit as st

from lastmile.dashboard.components.forecast_panels import (
    hour_label,
    render_calibration,
    render_evaluation_table,
    render_outlook_cards,
    render_risk_outlook,
    render_skill_by_horizon,
    render_watchlist,
)
from lastmile.forecasting import metrics as fc
from lastmile.metrics import Metrics
from lastmile.settings import get_settings

SPACER = '<div style="height: 0.85rem;"></div>'


def render(metrics_svc: Metrics) -> None:
    try:
        forecast = fc.load_predictions(metrics_svc.conn)
    except Exception as exc:
        st.error(f"Failed to load forecasts: {exc}")
        return

    if forecast.empty:
        st.warning(
            "No forecasts stored yet. Generate them with "
            "`lastmile forecast --all` (weather first: `lastmile weather`)."
        )
        return

    origin = forecast["origin_timestamp"].iloc[0]
    model_version = forecast["model_version"].iloc[0]
    st.caption(
        f"Forecast from the {hour_label(origin)} snapshot on {origin[:10]} · "
        f"model `{model_version}` · trained and scored offline by "
        "`lastmile forecast`"
    )

    outlook = fc.forecast_outlook(forecast)
    watchlist = fc.forecast_watchlist(forecast)

    render_outlook_cards(outlook, get_settings().forecast_risk_threshold)
    st.markdown(SPACER, unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        render_watchlist(watchlist, get_settings().forecast_risk_threshold)
    with right:
        render_risk_outlook(outlook)

    st.markdown(SPACER, unsafe_allow_html=True)
    _render_validation(metrics_svc)


def _render_validation(metrics_svc: Metrics) -> None:
    st.subheader("Does the forecast actually work?")
    st.caption(
        "Rolling-origin backtest: each fold is trained only on hours before "
        "the window it is scored on, then compared against two references — "
        "**persistence** (assume the station stays as it is) and "
        "**climatology** (its own stockout rate at this hour over the last "
        "four weeks)."
    )

    try:
        evaluation = fc.load_metrics(metrics_svc.conn)
        calibration = fc.load_calibration(metrics_svc.conn)
    except Exception as exc:
        st.error(f"Failed to load backtest results: {exc}")
        return

    if evaluation.empty:
        st.info(
            "No backtest results stored. Run `lastmile forecast --backtest`."
        )
        return

    choice = st.segmented_control(
        "Failure mode",
        options=["Empty", "Full"],
        default="Empty",
        label_visibility="collapsed",
    )
    target = (choice or "Empty").lower()

    left, right = st.columns(2)
    with left:
        render_skill_by_horizon(evaluation, target)
    with right:
        render_calibration(calibration, target)

    with st.expander("Full backtest scores"):
        render_evaluation_table(evaluation)
        st.caption(
            "Brier and log loss are lower-is-better; PR-AUC and ROC-AUC are "
            "higher-is-better. PR-AUC is the honest headline here because "
            "stockouts are rare, so accuracy and ROC-AUC both flatter a model "
            "that mostly predicts 'fine'."
        )
