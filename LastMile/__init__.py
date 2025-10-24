"""
LastMile - A Python library for managing GBSP transportation data.

This library provides tools for ingesting, processing, and analyzing
bike share and other last-mile transportation data from various APIs.

The library is organized into four main classes:
- LastMileSetup: For initial setup and configuration
- LastMileManager: For ongoing data management and updates
- LastMileUtils: For common utility functions (JSON loading, database operations)
- LastMileMetrics: For metrics calculations and analysis
"""

from .lastmile_setup import LastMileSetup
from .lastmile_manager import LastMileManager
from .lastmile_utils import LastMileUtils
from .lastmile_metrics import LastMileMetrics

__version__ = "1.0.0alpha"
__author__ = "Leonardo Barleta"
__all__ = ["LastMileSetup", "LastMileManager", "LastMileUtils", "LastMileMetrics"]