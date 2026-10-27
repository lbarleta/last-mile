"""
Internal constants: things the code depends on structurally rather than
things a deployment would want to change.

Anything tunable belongs in ``lastmile.toml`` — see :mod:`lastmile.settings`.
"""

from __future__ import annotations

# Hourly snapshot key used across the app, its cache keys, and the metric layer.
# Stored as a real DATETIME; this is the form it takes above the storage layer.
TIMESTAMP_FORMAT = "%Y-%m-%d-%H:00"

# Columns written by the collector, in the order the DDL declares them.
STATION_COLUMNS = (
    "station_id",
    "ts",
    "num_bikes_available",
    "num_docks_available",
    "num_ebikes_available",
    "num_docks_disabled",
    "num_bikes_disabled",
    "is_installed",
    "is_renting",
    "is_returning",
    "last_reported",
)
BIKE_COLUMNS = (
    "bike_id",
    "ts",
    "lat",
    "lon",
    "is_reserved",
    "is_disabled",
    "vehicle_type_id",
    "current_range_meters",
    "last_reported",
)

# GBFS propulsion types that count as an "e-bike" for the dashboard's purposes.
ELECTRIC_PROPULSION = frozenset({"electric", "electric_assist"})

# Free-floating bikes have coordinates but no region, and are overwhelmingly
# concentrated in San Francisco, so they are all attributed there.
FREE_FLOATING_REGION = "San Francisco"
