"""
Stockout forecasting — a stub.

Intended to predict, per station, the probability of running empty or full over
the next several hours. Nothing is implemented: this package is the wiring that
``lastmile forecast`` calls, and the warehouse holds no forecast tables.
"""

from __future__ import annotations

from ..db import Db

MESSAGE = "stockout forecasting is not implemented"


def train(conn: Db, **kwargs) -> None:
    """Fit the stockout model. Not implemented."""
    raise NotImplementedError(MESSAGE)


def backtest(conn: Db, **kwargs) -> None:
    """Evaluate the model on held-out folds. Not implemented."""
    raise NotImplementedError(MESSAGE)


def score(conn: Db, **kwargs) -> None:
    """Score the most recent snapshot hour. Not implemented."""
    raise NotImplementedError(MESSAGE)


__all__ = ["MESSAGE", "backtest", "score", "train"]
