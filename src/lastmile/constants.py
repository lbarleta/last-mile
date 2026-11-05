"""
Internal constants: things the code depends on structurally rather than
things a deployment would want to change.

Anything tunable belongs in ``lastmile.toml`` — see :mod:`lastmile.settings`.
Table and column names live in :mod:`lastmile.db.schema`.
"""

from __future__ import annotations

# Hourly snapshot key used across the app, its cache keys, and the metric layer.
# A local wall-clock label in the collected system's zone; the lake stores the
# instant behind it (see lastmile.db), and this is the form it takes above.
TIMESTAMP_FORMAT = "%Y-%m-%d-%H:00"

# GBFS propulsion types that count as electric. Used to split the per-type
# availability counts into electric and the rest.
ELECTRIC_PROPULSION = ("electric", "electric_assist")

# Free-floating vehicles have coordinates but no region in GBFS, so the region
# breakdowns attribute them all to one. The remaining Bay Wheels–specific
# default in the package: a system with differently named regions wants this
# changed, and a docked-only system never reaches it.
FREE_FLOATING_REGION = "San Francisco"
