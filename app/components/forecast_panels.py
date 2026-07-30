"""Panels for the stockout forecast view."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

TIMESTAMP_FORMAT = "%Y-%m-%d-%H:00"

EMPTY_COLOR = "#b42828"
FULL_COLOR = "#285ab4"
MODEL_COLORS = {
    "Model": "#1f6f54",
    "Persistence": "#7a828a",
    "Climatology": "#dc8c28",
}
MODEL_LABELS = {
    "gbm": "Model",
    "persistence": "Persistence",
    "climatology": "Climatology",
}

_PANEL_CSS = """
<style>
  div[data-testid="stElementContainer"]:has(.lm-fc-head) {
    margin-bottom: 1.15rem !important;
  }
  .lm-fc-head { margin: 0; }
  .lm-fc-title {
    font-size: 1.05rem;
    font-weight: 600;
    color: #1c1f24;
    line-height: 1.3;
    margin: 0;
  }
  .lm-fc-caption {
    font-size: 0.85rem;
    color: #7a828a;
    margin: 0.15rem 0 0 0;
    line-height: 1.3;
  }
  .lm-fc-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.65rem;
    margin-bottom: 0.75rem;
  }
  .lm-fc-card {
    border: 1px solid #d5d9de;
    border-radius: 8px;
    background: #ffffff;
    padding: 0.75rem 0.85rem;
    min-height: 4.5rem;
  }
  .lm-fc-card-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #5c636b;
    margin-bottom: 0.35rem;
  }
  .lm-fc-card-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: #1c1f24;
    line-height: 1.25;
  }
  .lm-fc-card-note {
    font-size: 0.78rem;
    color: #6b7280;
    margin-top: 0.15rem;
  }
</style>
"""


def _panel_head(title: str, caption: str) -> None:
    st.markdown(
        f"""{_PANEL_CSS}
        <div class="lm-fc-head">
          <div class="lm-fc-title">{title}</div>
          <div class="lm-fc-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def hour_label(timestamp: Optional[str]) -> str:
    if not timestamp:
        return "—"
    try:
        dt = datetime.strptime(timestamp, TIMESTAMP_FORMAT)
    except ValueError:
        return str(timestamp)
    return dt.strftime("%-I %p").lower()


def render_outlook_cards(outlook: pd.DataFrame, threshold: float) -> None:
    """Headline counts for the riskiest hour in the forecast window."""
    st.markdown(_PANEL_CSS, unsafe_allow_html=True)
    if outlook.empty:
        st.info("No forecast available.")
        return

    peak_empty = outlook.loc[outlook["at_risk_empty"].idxmax()]
    peak_full = outlook.loc[outlook["at_risk_full"].idxmax()]
    horizon_end = outlook["target_timestamp"].iloc[-1]
    expected_total = float(
        outlook["expected_empty"].max() + outlook["expected_full"].max()
    )

    cards = [
        (
            "Peak empty risk",
            f"{int(peak_empty['at_risk_empty'])} stations",
            f"at {hour_label(peak_empty['target_timestamp'])} "
            f"(+{int(peak_empty['horizon'])}h)",
        ),
        (
            "Peak full risk",
            f"{int(peak_full['at_risk_full'])} stations",
            f"at {hour_label(peak_full['target_timestamp'])} "
            f"(+{int(peak_full['horizon'])}h)",
        ),
        (
            "Expected stockouts",
            f"{expected_total:,.0f}",
            "sum of probabilities at the worst hour",
        ),
        (
            "Forecast window",
            f"through {hour_label(horizon_end)}",
            f"risk threshold {threshold:.0%}",
        ),
    ]
    html = "".join(
        f"""<div class="lm-fc-card">
              <div class="lm-fc-card-label">{label}</div>
              <div class="lm-fc-card-value">{value}</div>
              <div class="lm-fc-card-note">{note}</div>
            </div>"""
        for label, value, note in cards
    )
    st.markdown(f'<div class="lm-fc-cards">{html}</div>', unsafe_allow_html=True)


def render_risk_outlook(outlook: pd.DataFrame) -> None:
    """Stations above the risk threshold at each hour ahead."""
    _panel_head(
        "Risk outlook",
        "Stations predicted to run empty or full at each hour ahead",
    )
    if outlook.empty:
        st.info("No forecast available.")
        return

    df = outlook[
        ["horizon", "target_timestamp", "at_risk_empty", "at_risk_full"]
    ].melt(
        id_vars=["horizon", "target_timestamp"],
        var_name="metric",
        value_name="at_risk",
    )
    df["issue"] = df["metric"].map(
        {"at_risk_empty": "Empty", "at_risk_full": "Full"}
    )
    df["hour"] = df["target_timestamp"].map(hour_label)
    order = outlook.sort_values("horizon")["target_timestamp"].map(hour_label).tolist()

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("hour:N", title="Forecast hour", sort=order),
            y=alt.Y("at_risk:Q", title="Stations at risk"),
            color=alt.Color(
                "issue:N",
                title=None,
                scale=alt.Scale(
                    domain=["Empty", "Full"], range=[EMPTY_COLOR, FULL_COLOR]
                ),
                legend=alt.Legend(orient="top-right", direction="horizontal"),
            ),
            xOffset=alt.XOffset("issue:N", sort=["Empty", "Full"]),
            tooltip=[
                alt.Tooltip("hour:N", title="Hour"),
                alt.Tooltip("horizon:Q", title="Hours ahead"),
                alt.Tooltip("issue:N", title="Risk"),
                alt.Tooltip("at_risk:Q", title="Stations"),
            ],
        )
        .properties(height=340, padding={"left": 4, "right": 12, "top": 4, "bottom": 8})
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, width="stretch")


def render_watchlist(watchlist: pd.DataFrame, threshold: float) -> None:
    """Ranked dispatch list of stations predicted to stock out."""
    _panel_head(
        "Dispatch watchlist",
        f"Stations with a ≥{threshold:.0%} chance of running empty or full in the "
        "next 6 hours · lead time is how long until the first crossing",
    )
    if watchlist.empty:
        st.info("No station crosses the risk threshold in this window.")
        return

    display = watchlist.copy()

    def _now_label(row: pd.Series) -> str:
        bikes, docks = row.get("bikes_now"), row.get("docks_now")
        if pd.isna(bikes) or pd.isna(docks):
            return "—"
        return f"{int(bikes)} bikes / {int(docks)} docks"

    display["Now"] = display.apply(_now_label, axis=1)
    display["Risk"] = display["peak_risk"].map(lambda v: f"{v:.0%}")
    display["When"] = display.apply(
        lambda r: f"{hour_label(r['first_hour'])} (+{int(r['lead_hours'])}h)", axis=1
    )
    display = display.rename(
        columns={"name": "Station", "region": "Region", "issue": "Risk of"}
    )

    st.dataframe(
        display[["Station", "Region", "Now", "Risk of", "Risk", "When"]],
        width="stretch",
        hide_index=True,
        height=455,
    )


def render_skill_by_horizon(metrics: pd.DataFrame, target: str) -> None:
    """How model skill decays as the forecast reaches further out."""
    _panel_head(
        "Skill by horizon",
        "Average precision on held-out folds — higher is better, and the gap "
        "over the baselines is the value the model adds",
    )
    df = metrics[(metrics["target"] == target) & (metrics["horizon"] > 0)]
    if df.empty:
        st.info("No backtest results yet. Run `python scripts/forecast.py --backtest`.")
        return

    df = (
        df.assign(model=df["model"].map(MODEL_LABELS).fillna(df["model"]))
        .groupby(["model", "horizon"], as_index=False)
        .agg(avg_precision=("avg_precision", "mean"))
    )
    chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("horizon:O", title="Hours ahead"),
            y=alt.Y("avg_precision:Q", title="Average precision"),
            color=alt.Color(
                "model:N",
                title=None,
                scale=alt.Scale(
                    domain=list(MODEL_COLORS), range=list(MODEL_COLORS.values())
                ),
                legend=alt.Legend(orient="top-right", direction="vertical"),
            ),
            tooltip=[
                alt.Tooltip("model:N", title="Model"),
                alt.Tooltip("horizon:O", title="Hours ahead"),
                alt.Tooltip("avg_precision:Q", title="Avg precision", format=".3f"),
            ],
        )
        .properties(height=300, padding={"left": 4, "right": 12, "top": 4, "bottom": 8})
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, width="stretch")


def render_calibration(calibration: pd.DataFrame, target: str) -> None:
    """Reliability diagram: do predicted probabilities match observed rates?"""
    _panel_head(
        "Calibration",
        "Predicted probability vs observed frequency — points on the diagonal "
        "mean a 70% risk really does happen about 70% of the time",
    )
    df = calibration[
        (calibration["target"] == target) & (calibration["model"] == "gbm")
    ]
    if df.empty:
        st.info("No calibration data yet. Run `python scripts/forecast.py --backtest`.")
        return

    reference = pd.DataFrame({"x": [0.0, 1.0], "y": [0.0, 1.0]})
    diagonal = (
        alt.Chart(reference)
        .mark_line(strokeDash=[4, 4], color="#c5ccd3")
        .encode(x=alt.X("x:Q"), y=alt.Y("y:Q"))
    )
    points = (
        alt.Chart(df)
        .mark_line(point=True, color=MODEL_COLORS["Model"])
        .encode(
            x=alt.X(
                "mean_predicted:Q",
                title="Predicted probability",
                scale=alt.Scale(domain=[0, 1]),
            ),
            y=alt.Y(
                "observed_rate:Q",
                title="Observed frequency",
                scale=alt.Scale(domain=[0, 1]),
            ),
            size=alt.Size("n_obs:Q", title="Observations", legend=None),
            tooltip=[
                alt.Tooltip("mean_predicted:Q", title="Predicted", format=".2f"),
                alt.Tooltip("observed_rate:Q", title="Observed", format=".2f"),
                alt.Tooltip("n_obs:Q", title="Observations", format=","),
            ],
        )
    )
    chart = (
        (diagonal + points)
        .properties(height=300, padding={"left": 4, "right": 12, "top": 4, "bottom": 8})
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, width="stretch")


def render_evaluation_table(metrics: pd.DataFrame) -> None:
    """Pooled backtest scores for the model and both baselines."""
    overall = metrics[metrics["horizon"] == 0]
    if overall.empty:
        st.info("No backtest results yet.")
        return

    summary = (
        overall.assign(
            Model=overall["model"].map(MODEL_LABELS).fillna(overall["model"]),
            Target=overall["target"].str.capitalize(),
        )
        .groupby(["Target", "Model"], as_index=False)
        .agg(
            base_rate=("base_rate", "mean"),
            brier=("brier", "mean"),
            log_loss=("log_loss", "mean"),
            avg_precision=("avg_precision", "mean"),
            roc_auc=("roc_auc", "mean"),
            n_obs=("n_obs", "sum"),
        )
    )
    order = {"Model": 0, "Persistence": 1, "Climatology": 2}
    summary = summary.sort_values(
        ["Target", "Model"], key=lambda s: s.map(order).fillna(s)
    )
    summary["Base rate"] = summary["base_rate"].map("{:.2%}".format)
    summary["Brier"] = summary["brier"].map("{:.4f}".format)
    summary["Log loss"] = summary["log_loss"].map("{:.4f}".format)
    summary["PR-AUC"] = summary["avg_precision"].map("{:.3f}".format)
    summary["ROC-AUC"] = summary["roc_auc"].map("{:.3f}".format)
    summary["Predictions"] = summary["n_obs"].map("{:,}".format)

    st.dataframe(
        summary[
            [
                "Target",
                "Model",
                "Base rate",
                "Brier",
                "Log loss",
                "PR-AUC",
                "ROC-AUC",
                "Predictions",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
