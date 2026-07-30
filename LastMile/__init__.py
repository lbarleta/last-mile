"""
LastMile - A Python library for managing GBFS transportation data.

Modules:
- config: defaults and constants
- utils: GBFS feed helpers and SQLite connection
- setup: one-time station table setup
- manager: hourly snapshot collection
- db: read-only query helpers and indexes
- metrics: live-ops and trends metrics
- coverage: San Francisco walk-shed coverage
- weather: Open-Meteo hourly weather cache
- features: feature engineering for stockout forecasting
- forecast: stockout model training, backtesting, and scoring

Public classes:
- LastMileSetup, LastMileManager, LastMileUtils, LastMileMetrics
"""

from .setup import LastMileSetup
from .manager import LastMileManager
from .utils import LastMileUtils
from .metrics import LastMileMetrics
from .config import DEFAULT_DB_PATH, DEFAULT_FEEDS_URL, DEFAULT_LANG, DEFAULT_TIMEZONE

__version__ = "1.0.0alpha"
__author__ = "Leonardo Barleta"
__all__ = [
    "LastMileSetup",
    "LastMileManager",
    "LastMileUtils",
    "LastMileMetrics",
    "DEFAULT_DB_PATH",
    "DEFAULT_FEEDS_URL",
    "DEFAULT_LANG",
    "DEFAULT_TIMEZONE",
]
