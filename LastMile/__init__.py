"""
LastMile - A Python library for managing GBFS transportation data.

Classes:
- LastMileSetup: initial setup and configuration
- LastMileManager: ongoing hourly data collection
- LastMileUtils: GBFS feed helpers and database connection
- LastMileMetrics: live-ops and historical metrics from SQLite
"""

from .lastmile_setup import LastMileSetup
from .lastmile_manager import LastMileManager
from .lastmile_utils import LastMileUtils
from .lastmile_metrics import LastMileMetrics
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
