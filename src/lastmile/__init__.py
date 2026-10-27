"""
LastMile — Bay Wheels GBFS collection and the operations dashboard over it.

Collection and the dashboard are one package: ``lastmile`` on the command line
drives the collect side, ``lastmile dashboard`` serves the read side, and both
read the same :mod:`lastmile.settings`.
"""

from __future__ import annotations

from .settings import Settings, get_settings, load_settings, reload_settings

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "Settings",
    "get_settings",
    "load_settings",
    "reload_settings",
]
