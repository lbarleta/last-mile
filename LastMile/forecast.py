"""Station stockout forecasting: train, backtest, score, and store.

Predicts, for every station and each of the next few hours, the probability
that it will be *empty* (no bikes to take) or *full* (no docks to return to).
These are the two states that actually strand a rider, and they are what the
Live Ops "problematic stations" table reports after the fact.

Two gradient-boosted classifiers are fit — one per failure mode — with the
forecast horizon as an input feature rather than a separate model per hour.
Everything is trained and scored offline by ``scripts/forecast.py``; the
dashboard only reads the resulting tables.

Accuracy claims are only meaningful against a reference, so
:func:`backtest` scores the model alongside two baselines on the same
rolling-origin splits:

* **persistence** — the empirical chance of a stockout given only whether the
  station is stocked out right now, and
* **climatology** — the station's own stockout rate at that hour of day over
  the trailing four weeks.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from .config import (
    FORECAST_HORIZONS,
    FORECAST_MAX_TRAIN_ROWS,
    FORECAST_MODEL_PATH,
    FORECAST_TRAIN_DAYS,
    FORECAST_WARMUP_DAYS,
    TIMESTAMP_FORMAT,
)
from . import features as feat

TARGETS = ("empty", "full")
BASELINES = ("persistence", "climatology")
MODEL_NAME = "gbm"


@dataclass
class ForecastBundle:
    """A trained pair of classifiers plus everything needed to reuse them."""

    models: Dict[str, Any]
    feature_names: list[str]
    categorical_features: list[str]
    persistence_rates: Dict[str, pd.DataFrame]
    version: str
    trained_at: str
    train_start: Optional[str]
    train_end: Optional[str]
    n_train_rows: int
    base_rates: Dict[str, float] = field(default_factory=dict)


# --- helpers --------------------------------------------------------------


def _shift_timestamp(timestamp: str, hours: int) -> str:
    dt = datetime.strptime(timestamp, TIMESTAMP_FORMAT) + timedelta(hours=hours)
    return dt.strftime(TIMESTAMP_FORMAT)


def _warmup_start(timestamp: str, days: int = FORECAST_WARMUP_DAYS) -> str:
    return _shift_timestamp(timestamp, -24 * days)


def _new_classifier(random_state: int = 7):
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        loss="log_loss",
        learning_rate=0.08,
        max_iter=300,
        max_leaf_nodes=31,
        min_samples_leaf=50,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=20,
        random_state=random_state,
    )


def _prepare_matrix(
    frame: pd.DataFrame, feature_names: Sequence[str]
) -> pd.DataFrame:
    x = frame[list(feature_names)].copy()
    for col in feat.CATEGORICAL_FEATURES:
        if col in x.columns:
            x[col] = pd.to_numeric(x[col], errors="coerce").fillna(0).astype("int32")
    return x


def _persistence_table(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    """
    Empirical P(stockout at t+h | stocked out at t) by horizon.

    Used as the naive reference: "assume nothing changes", expressed as a
    calibrated probability rather than a hard 0/1 so it can be scored with the
    same metrics as the model.
    """
    state_col = "is_empty" if target == "empty" else "is_full"
    label_col = f"y_{target}"
    df = frame[[state_col, "horizon", label_col]].dropna()
    if df.empty:
        return pd.DataFrame(columns=["horizon", "state", "rate"])
    grouped = (
        df.assign(state=df[state_col].astype(int))
        .groupby(["horizon", "state"], as_index=False)[label_col]
        .mean()
        .rename(columns={label_col: "rate"})
    )
    return grouped


def _apply_persistence(
    frame: pd.DataFrame, table: pd.DataFrame, target: str
) -> np.ndarray:
    state_col = "is_empty" if target == "empty" else "is_full"
    if table.empty:
        return np.full(len(frame), np.nan)
    lookup = {
        (int(row.horizon), int(row.state)): float(row.rate)
        for row in table.itertuples(index=False)
    }
    fallback = float(table["rate"].mean())
    states = frame[state_col].fillna(0).astype(int).to_numpy()
    horizons = frame["horizon"].astype(int).to_numpy()
    return np.array(
        [lookup.get((h, s), fallback) for h, s in zip(horizons, states)],
        dtype=float,
    )


# --- training -------------------------------------------------------------


def train(
    conn: sqlite3.Connection,
    *,
    train_days: Optional[int] = FORECAST_TRAIN_DAYS,
    horizons: Sequence[int] = FORECAST_HORIZONS,
    max_rows: int = FORECAST_MAX_TRAIN_ROWS,
    end_timestamp: Optional[str] = None,
    verbose: bool = False,
) -> ForecastBundle:
    """Fit the empty/full classifiers on the most recent ``train_days``."""
    from . import db as queries

    end = end_timestamp or queries.get_latest_timestamp(conn)
    if end is None:
        raise ValueError("No snapshots available to train on")

    start = _shift_timestamp(end, -24 * train_days) if train_days else None
    load_since = _warmup_start(start) if start else None

    panel = feat.load_panel(conn, since=load_since)
    origin_rows = _rows_between(panel, start, end)
    frame = feat.build_features(
        panel, horizons=horizons, origin_rows=origin_rows, max_rows=max_rows
    )
    if frame.empty:
        raise ValueError("No usable training rows in the requested window")

    feature_names = feat.feature_columns(frame)
    x = _prepare_matrix(frame, feature_names)
    categorical = [c for c in feat.CATEGORICAL_FEATURES if c in feature_names]

    models, persistence, base_rates = {}, {}, {}
    for target in TARGETS:
        y = frame[f"y_{target}"].to_numpy()
        clf = _new_classifier()
        clf.set_params(categorical_features=categorical)
        clf.fit(x, y)
        models[target] = clf
        persistence[target] = _persistence_table(frame, target)
        base_rates[target] = float(y.mean())
        if verbose:
            print(
                f"  {target}: {len(y):,} rows, base rate {base_rates[target]:.3%}, "
                f"{clf.n_iter_} boosting iterations"
            )

    return ForecastBundle(
        models=models,
        feature_names=feature_names,
        categorical_features=categorical,
        persistence_rates=persistence,
        version=datetime.now().strftime("%Y%m%d-%H%M%S"),
        trained_at=datetime.now().isoformat(timespec="seconds"),
        train_start=start,
        train_end=end,
        n_train_rows=int(len(frame)),
        base_rates=base_rates,
    )


def _rows_between(
    panel: feat.StationPanel, start: Optional[str], end: Optional[str]
) -> np.ndarray:
    rows = np.arange(panel.n_hours)
    if start is not None:
        rows = rows[panel.timestamps[rows] >= start]
    if end is not None:
        rows = rows[panel.timestamps[rows] <= end]
    return rows


def save_bundle(bundle: ForecastBundle, path: str = FORECAST_MODEL_PATH) -> str:
    import joblib
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    return path


def load_bundle(path: str = FORECAST_MODEL_PATH) -> ForecastBundle:
    import joblib

    return joblib.load(path)


# --- scoring --------------------------------------------------------------


def predict(bundle: ForecastBundle, frame: pd.DataFrame) -> pd.DataFrame:
    """Attach ``p_empty`` / ``p_full`` columns to a feature frame."""
    x = _prepare_matrix(frame, bundle.feature_names)
    out = frame.copy()
    for target in TARGETS:
        out[f"p_{target}"] = bundle.models[target].predict_proba(x)[:, 1]
    return out


def score_origin(
    conn: sqlite3.Connection,
    bundle: ForecastBundle,
    *,
    origin_timestamp: Optional[str] = None,
    horizons: Sequence[int] = FORECAST_HORIZONS,
) -> pd.DataFrame:
    """
    Forecast every station forward from one snapshot hour.

    The grid is extended past the last snapshot so target-hour weather (from
    the Open-Meteo forecast window) and calendar features are available.
    """
    from . import db as queries

    origin = origin_timestamp or queries.get_latest_timestamp(conn)
    if origin is None:
        raise ValueError("No snapshots available to score")

    max_h = max(horizons)
    panel = feat.load_panel(
        conn, since=_warmup_start(origin), extend_hours=max_h
    )
    row = panel.row_of(origin)
    if row is None:
        raise ValueError(f"Snapshot {origin} not found")

    frame = feat.build_features(
        panel,
        horizons=horizons,
        origin_rows=np.array([row]),
        with_labels=False,
    )
    if frame.empty:
        return pd.DataFrame()

    scored = predict(bundle, frame)
    names = panel.stations.set_index("station_id")
    scored["name"] = scored["station_id"].map(names["name"])
    scored["region"] = scored["station_id"].map(names["region"])
    return scored


# --- backtesting ----------------------------------------------------------


def _metric_row(
    y: np.ndarray, p: np.ndarray, **meta
) -> Optional[Dict[str, Any]]:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    mask = ~np.isnan(p)
    y, p = y[mask], np.clip(p[mask], 1e-6, 1 - 1e-6)
    if y.size == 0 or len(np.unique(y)) < 2:
        return None
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return {
        **meta,
        "n_obs": int(y.size),
        "base_rate": float(y.mean()),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": log_loss,
        "avg_precision": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
    }


def _calibration_rows(
    y: np.ndarray, p: np.ndarray, bins: int = 10, **meta
) -> list[Dict[str, Any]]:
    mask = ~np.isnan(p)
    y, p = y[mask], p[mask]
    if y.size == 0:
        return []
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    rows = []
    for b in range(bins):
        sel = idx == b
        if not sel.any():
            continue
        rows.append(
            {
                **meta,
                "bin_lower": float(edges[b]),
                "bin_upper": float(edges[b + 1]),
                "n_obs": int(sel.sum()),
                "mean_predicted": float(p[sel].mean()),
                "observed_rate": float(y[sel].mean()),
            }
        )
    return rows


def backtest(
    conn: sqlite3.Connection,
    *,
    n_folds: int = 4,
    fold_days: int = 7,
    train_days: Optional[int] = 120,
    horizons: Sequence[int] = FORECAST_HORIZONS,
    max_rows: int = 400_000,
    verbose: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Rolling-origin evaluation of the model against both baselines.

    Each fold trains only on hours strictly before the fold window, so no
    future information reaches the fitted model. Returns per-fold metrics and
    pooled calibration bins.
    """
    from . import db as queries

    latest = queries.get_latest_timestamp(conn)
    if latest is None:
        raise ValueError("No snapshots available to backtest")

    folds = []
    for i in range(n_folds):
        fold_end = _shift_timestamp(latest, -24 * fold_days * i)
        fold_start = _shift_timestamp(fold_end, -24 * fold_days + 1)
        folds.append((fold_start, fold_end))
    folds.reverse()

    earliest_train = (
        _shift_timestamp(folds[0][0], -24 * train_days) if train_days else None
    )
    panel = feat.load_panel(
        conn, since=_warmup_start(earliest_train) if earliest_train else None
    )

    metric_rows: list[Dict[str, Any]] = []
    calibration_rows: list[Dict[str, Any]] = []

    for fold_idx, (fold_start, fold_end) in enumerate(folds):
        train_end = _shift_timestamp(fold_start, -max(horizons) - 1)
        train_start = (
            _shift_timestamp(train_end, -24 * train_days) if train_days else None
        )
        train_rows = _rows_between(panel, train_start, train_end)
        test_rows = _rows_between(panel, fold_start, fold_end)
        if train_rows.size == 0 or test_rows.size == 0:
            continue

        if verbose:
            print(
                f"  fold {fold_idx + 1}/{len(folds)}: "
                f"train ≤ {train_end}, test {fold_start} → {fold_end}"
            )

        train_frame = feat.build_features(
            panel, horizons=horizons, origin_rows=train_rows, max_rows=max_rows
        )
        test_frame = feat.build_features(
            panel, horizons=horizons, origin_rows=test_rows
        )
        if train_frame.empty or test_frame.empty:
            continue

        feature_names = feat.feature_columns(train_frame)
        categorical = [c for c in feat.CATEGORICAL_FEATURES if c in feature_names]
        x_train = _prepare_matrix(train_frame, feature_names)
        x_test = _prepare_matrix(test_frame, feature_names)

        for target in TARGETS:
            y_train = train_frame[f"y_{target}"].to_numpy()
            y_test = test_frame[f"y_{target}"].to_numpy()

            clf = _new_classifier()
            clf.set_params(categorical_features=categorical)
            clf.fit(x_train, y_train)

            predictions = {
                MODEL_NAME: clf.predict_proba(x_test)[:, 1],
                "climatology": test_frame[f"base_clim_{target}"].to_numpy(dtype=float),
                "persistence": _apply_persistence(
                    test_frame, _persistence_table(train_frame, target), target
                ),
            }

            for name, p in predictions.items():
                overall = _metric_row(
                    y_test,
                    p,
                    fold=fold_idx,
                    fold_start=fold_start,
                    fold_end=fold_end,
                    target=target,
                    model=name,
                    horizon=0,
                )
                if overall:
                    metric_rows.append(overall)
                for horizon in horizons:
                    sel = (test_frame["horizon"] == horizon).to_numpy()
                    row = _metric_row(
                        y_test[sel],
                        p[sel],
                        fold=fold_idx,
                        fold_start=fold_start,
                        fold_end=fold_end,
                        target=target,
                        model=name,
                        horizon=int(horizon),
                    )
                    if row:
                        metric_rows.append(row)

                calibration_rows.extend(
                    _calibration_rows(y_test, p, target=target, model=name)
                )

    metrics = pd.DataFrame(metric_rows)
    calibration = pd.DataFrame(calibration_rows)
    if not calibration.empty:
        calibration = (
            calibration.assign(
                weighted_pred=calibration["mean_predicted"] * calibration["n_obs"],
                weighted_obs=calibration["observed_rate"] * calibration["n_obs"],
            )
            .groupby(["target", "model", "bin_lower", "bin_upper"], as_index=False)
            .agg(
                n_obs=("n_obs", "sum"),
                weighted_pred=("weighted_pred", "sum"),
                weighted_obs=("weighted_obs", "sum"),
            )
        )
        calibration["mean_predicted"] = (
            calibration["weighted_pred"] / calibration["n_obs"]
        )
        calibration["observed_rate"] = (
            calibration["weighted_obs"] / calibration["n_obs"]
        )
        calibration = calibration.drop(columns=["weighted_pred", "weighted_obs"])
    return metrics, calibration


# --- storage --------------------------------------------------------------


def ensure_forecast_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS forecast_stockout (
            origin_timestamp TEXT NOT NULL,
            target_timestamp TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            station_id TEXT NOT NULL,
            p_empty REAL,
            p_full REAL,
            bikes_now REAL,
            docks_now REAL,
            model_version TEXT,
            created_at TEXT,
            PRIMARY KEY (origin_timestamp, station_id, horizon)
        );

        CREATE INDEX IF NOT EXISTS idx_forecast_origin
            ON forecast_stockout(origin_timestamp);

        CREATE TABLE IF NOT EXISTS forecast_metrics (
            model_version TEXT NOT NULL,
            created_at TEXT,
            fold INTEGER,
            fold_start TEXT,
            fold_end TEXT,
            target TEXT,
            model TEXT,
            horizon INTEGER,
            n_obs INTEGER,
            base_rate REAL,
            brier REAL,
            log_loss REAL,
            avg_precision REAL,
            roc_auc REAL
        );

        CREATE TABLE IF NOT EXISTS forecast_calibration (
            model_version TEXT NOT NULL,
            created_at TEXT,
            target TEXT,
            model TEXT,
            bin_lower REAL,
            bin_upper REAL,
            n_obs INTEGER,
            mean_predicted REAL,
            observed_rate REAL
        );
        """
    )
    conn.commit()


def write_predictions(
    conn: sqlite3.Connection, scored: pd.DataFrame, model_version: str
) -> int:
    """Replace stored predictions for the scored origin hour."""
    if scored.empty:
        return 0
    ensure_forecast_tables(conn)
    created_at = datetime.now().isoformat(timespec="seconds")
    origin = scored["origin_timestamp"].iloc[0]
    conn.execute(
        "DELETE FROM forecast_stockout WHERE origin_timestamp = ?", (origin,)
    )
    rows = [
        (
            row.origin_timestamp,
            row.target_timestamp,
            int(row.horizon),
            row.station_id,
            float(row.p_empty),
            float(row.p_full),
            None if pd.isna(row.bikes) else float(row.bikes),
            None if pd.isna(row.docks) else float(row.docks),
            model_version,
            created_at,
        )
        for row in scored.itertuples(index=False)
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO forecast_stockout (
            origin_timestamp, target_timestamp, horizon, station_id,
            p_empty, p_full, bikes_now, docks_now, model_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def write_evaluation(
    conn: sqlite3.Connection,
    metrics: pd.DataFrame,
    calibration: pd.DataFrame,
    model_version: str,
) -> None:
    """Store backtest results, replacing any previous run for this version."""
    ensure_forecast_tables(conn)
    created_at = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM forecast_metrics WHERE model_version = ?", (model_version,))
    conn.execute(
        "DELETE FROM forecast_calibration WHERE model_version = ?", (model_version,)
    )
    if not metrics.empty:
        out = metrics.assign(model_version=model_version, created_at=created_at)
        out.to_sql("forecast_metrics", conn, if_exists="append", index=False)
    if not calibration.empty:
        out = calibration.assign(model_version=model_version, created_at=created_at)
        out.to_sql("forecast_calibration", conn, if_exists="append", index=False)
    conn.commit()


def latest_forecast_origin(conn: sqlite3.Connection) -> Optional[str]:
    ensure_forecast_tables(conn)
    row = conn.execute(
        "SELECT MAX(origin_timestamp) FROM forecast_stockout"
    ).fetchone()
    return row[0] if row and row[0] else None


def load_predictions(
    conn: sqlite3.Connection, origin_timestamp: Optional[str] = None
) -> pd.DataFrame:
    """Stored predictions for one origin hour, joined to station metadata."""
    ensure_forecast_tables(conn)
    origin = origin_timestamp or latest_forecast_origin(conn)
    if origin is None:
        return pd.DataFrame()

    from . import db as queries

    name_col = queries._station_name_expr(conn)
    return pd.read_sql_query(
        f"""
        SELECT f.origin_timestamp, f.target_timestamp, f.horizon, f.station_id,
               f.p_empty, f.p_full, f.bikes_now, f.docks_now, f.model_version,
               {name_col} AS name,
               COALESCE(s.region, 'Unknown') AS region,
               s.capacity, s.lat, s.lon
        FROM forecast_stockout f
        LEFT JOIN stations s ON s.station_id = f.station_id
        WHERE f.origin_timestamp = ?
        ORDER BY f.horizon, f.station_id
        """,
        conn,
        params=(origin,),
    )


def load_metrics(conn: sqlite3.Connection) -> pd.DataFrame:
    """Backtest metrics for the most recent evaluated model version."""
    ensure_forecast_tables(conn)
    row = conn.execute(
        "SELECT model_version FROM forecast_metrics ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return pd.DataFrame()
    return pd.read_sql_query(
        "SELECT * FROM forecast_metrics WHERE model_version = ?",
        conn,
        params=(row[0],),
    )


def load_calibration(conn: sqlite3.Connection) -> pd.DataFrame:
    ensure_forecast_tables(conn)
    row = conn.execute(
        "SELECT model_version FROM forecast_calibration "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return pd.DataFrame()
    return pd.read_sql_query(
        "SELECT * FROM forecast_calibration WHERE model_version = ? "
        "ORDER BY target, model, bin_lower",
        conn,
        params=(row[0],),
    )
