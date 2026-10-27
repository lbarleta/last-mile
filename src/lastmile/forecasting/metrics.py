"""
Read side of the stockout forecast: what the dashboard consumes.

Deliberately light — pandas and the database only. Training and scoring live in
:mod:`lastmile.forecasting.model`, which is the half that needs the optional
``forecast`` extra (scikit-learn, joblib).
"""

from __future__ import annotations

import pandas as pd

from ..db import Db, key_expr, to_dt, to_key
from ..db.schema import create_statements, ensure_indexes
from ..settings import get_settings


def ensure_forecast_tables(conn: Db) -> None:
    for statement in create_statements():
        if "CREATE TABLE IF NOT EXISTS forecast_" in statement:
            conn.execute(statement)
    conn.commit()
    ensure_indexes(conn)


def latest_forecast_origin(conn: Db) -> str | None:
    ensure_forecast_tables(conn)
    row = conn.fetchone("SELECT MAX(origin_ts) FROM forecast_stockout")
    return to_key(row[0]) if row and row[0] else None


def load_predictions(
    conn: Db, origin_timestamp: str | None = None
) -> pd.DataFrame:
    """Stored predictions for one origin hour, joined to station metadata."""
    ensure_forecast_tables(conn)
    origin = origin_timestamp or latest_forecast_origin(conn)
    if origin is None:
        return pd.DataFrame()

    origin_key = key_expr("f.origin_ts")
    target_key = key_expr("f.target_ts")
    return conn.read_sql(
        f"""
        SELECT {origin_key} AS origin_timestamp,
               {target_key} AS target_timestamp,
               f.horizon, f.station_id,
               f.p_empty, f.p_full, f.bikes_now, f.docks_now, f.model_version,
               s.name AS name,
               COALESCE(s.region, 'Unknown') AS region,
               s.capacity, s.lat, s.lon
        FROM forecast_stockout f
        LEFT JOIN stations s ON s.station_id = f.station_id
        WHERE f.origin_ts = ?
        ORDER BY f.horizon, f.station_id
        """,
        (to_dt(origin),),
    )


def load_metrics(conn: Db) -> pd.DataFrame:
    """Backtest metrics for the most recent evaluated model version."""
    ensure_forecast_tables(conn)
    row = conn.fetchone(
        "SELECT model_version FROM forecast_metrics ORDER BY created_at DESC LIMIT 1"
    )
    if not row:
        return pd.DataFrame()
    return conn.read_sql(
        "SELECT * FROM forecast_metrics WHERE model_version = ?", (row[0],)
    )


def load_calibration(conn: Db) -> pd.DataFrame:
    ensure_forecast_tables(conn)
    row = conn.fetchone(
        "SELECT model_version FROM forecast_calibration "
        "ORDER BY created_at DESC LIMIT 1"
    )
    if not row:
        return pd.DataFrame()
    return conn.read_sql(
        "SELECT * FROM forecast_calibration WHERE model_version = ? "
        "ORDER BY target, model, bin_lower",
        (row[0],),
    )


def forecast_outlook(
    forecast: pd.DataFrame, threshold: float | None = None
) -> pd.DataFrame:
    """Count of stations above the risk threshold at each forecast hour."""
    if threshold is None:
        threshold = get_settings().forecast_risk_threshold
    if forecast.empty:
        return pd.DataFrame(
            columns=["horizon", "target_timestamp", "at_risk_empty", "at_risk_full"]
        )
    return (
        forecast.assign(
            at_risk_empty=(forecast["p_empty"] >= threshold).astype(int),
            at_risk_full=(forecast["p_full"] >= threshold).astype(int),
        )
        .groupby(["horizon", "target_timestamp"], as_index=False)
        .agg(
            at_risk_empty=("at_risk_empty", "sum"),
            at_risk_full=("at_risk_full", "sum"),
            expected_empty=("p_empty", "sum"),
            expected_full=("p_full", "sum"),
            stations=("station_id", "count"),
        )
        .sort_values("horizon")
    )


def forecast_watchlist(
    forecast: pd.DataFrame, threshold: float | None = None
) -> pd.DataFrame:
    """
    Stations predicted to run empty or full, ranked by peak risk.

    ``lead_hours`` is how far ahead the first threshold crossing is — the
    dispatch window an operator actually has.
    """
    if threshold is None:
        threshold = get_settings().forecast_risk_threshold
    columns = [
        "station_id",
        "name",
        "region",
        "bikes_now",
        "docks_now",
        "issue",
        "peak_risk",
        "lead_hours",
        "first_hour",
    ]
    if forecast.empty:
        return pd.DataFrame(columns=columns)

    flagged = forecast[
        (forecast["p_empty"] >= threshold) | (forecast["p_full"] >= threshold)
    ]
    if flagged.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for station_id, group in flagged.groupby("station_id", sort=False):
        group = group.sort_values("horizon")
        peak_empty = float(group["p_empty"].max())
        peak_full = float(group["p_full"].max())
        issue = "Empty" if peak_empty >= peak_full else "Full"
        risk_col = "p_empty" if issue == "Empty" else "p_full"
        crossing = group[group[risk_col] >= threshold]
        if crossing.empty:
            crossing = group
        first = crossing.iloc[0]
        head = group.iloc[0]
        rows.append(
            {
                "station_id": station_id,
                "name": head.get("name") or station_id,
                "region": head.get("region") or "Unknown",
                "bikes_now": head.get("bikes_now"),
                "docks_now": head.get("docks_now"),
                "issue": issue,
                "peak_risk": max(peak_empty, peak_full),
                "lead_hours": int(first["horizon"]),
                "first_hour": first["target_timestamp"],
            }
        )

    out = pd.DataFrame(rows, columns=columns)
    return out.sort_values(
        ["peak_risk", "lead_hours"], ascending=[False, True]
    ).reset_index(drop=True)
