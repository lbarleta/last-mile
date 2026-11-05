"""
Laying out a lake and loading it for the first time.

``lastmile init-db`` lands here: create every declared dataset, then pull the
slow-changing reference feeds once so the lake knows which system it holds —
its name, spec version and, above all, its timezone, which is what every local
hour is rendered in from then on. Safe to run repeatedly; a second run only
logs whatever reference data changed.

The hourly status feeds are :mod:`lastmile.collect`'s business; this module
borrows its reference loader rather than duplicating it.
"""

from __future__ import annotations

from . import Db
from .schema import HOURLY_TABLES, create_all


def init_db(conn: Db, client=None) -> dict:
    """
    Lay out the lake and load reference data.

    Returns the system's own description of itself (``system``), the zone the
    lake will render in (``timezone``) and the per-feed reference counts
    (``reference``). ``client`` is a :class:`lastmile.gbfs.GbfsClient`; the
    configured feed is used when none is given.
    """
    from ..collect import refresh_reference_data
    from ..gbfs import GbfsClient

    create_all(conn)
    client = client or GbfsClient()
    reference = refresh_reference_data(conn, client)
    return {
        "system": client.system_information(),
        "timezone": conn.timezone,
        "reference": reference,
    }


def is_initialized(conn: Db) -> bool:
    """
    True when the datasets exist and reference data has been loaded.

    ``system_information`` is the signal rather than the station tables, because
    an entirely free-floating system legitimately has none of those.
    """
    for name in ("system_information", *HOURLY_TABLES):
        if not conn.has_table(name):
            return False
    return conn.count("system_information") > 0
