"""
GBFS feed client.

Feed parsing normalizes the places where GBFS publishers disagree, so the rest
of the package sees one consistent shape:

* ``num_ebikes_available`` is a Lyft extension, not part of GBFS. The spec way
  to count electric bikes is ``vehicle_types_available`` cross-referenced with
  the ``vehicle_types`` feed, which is what this reads when it is available.
* ``vehicle_type_id`` is kept as text. Lyft happens to publish ``"1"``/``"2"``
  but Spin and Bird publish UUIDs.
* ``is_reserved`` / ``is_disabled`` arrive as integers from Lyft and as real
  booleans from Spin, and are coerced to 0/1 either way.

This talks to the network only. Storing what it returns is
:mod:`lastmile.collect`'s job.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd
import requests

from .constants import ELECTRIC_PROPULSION
from .settings import get_settings


def as_int_flag(value: Any) -> int | None:
    """GBFS publishers use both 0/1 and true/false for these flags."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class GbfsClient:
    """Reads the discovery document and the feeds it advertises."""

    def __init__(
        self,
        feeds_url: str | None = None,
        lang: str | None = None,
        timeout: int | None = None,
    ):
        """
        Args:
            feeds_url: URL of the GBFS discovery document. Defaults to the
                configured ``feeds_url``.
            lang: Feed language code.
            timeout: Per-request timeout in seconds.
        """
        settings = get_settings()
        self.feeds_url = feeds_url or settings.feeds_url
        self.lang = lang or settings.feeds_lang
        self.timeout = timeout if timeout is not None else settings.request_timeout_s
        self.feeds = self.get_system_feeds()
        self._vehicle_types: pd.DataFrame | None = None

    # --- feeds ------------------------------------------------------------

    def get_system_feeds(self) -> list[dict[str, Any]]:
        """Feed list from the GBFS discovery document."""
        sources = requests.get(self.feeds_url, timeout=self.timeout).json()
        data = sources["data"]
        # Single-language feeds sometimes omit the language envelope.
        block = data.get(self.lang) or next(iter(data.values()))
        return block["feeds"]

    def get_feed_url(self, name: str) -> str:
        for feed in self.feeds:
            if feed["name"] == name:
                return feed["url"]
        raise KeyError(f"Feed '{name}' not found in available feeds.")

    def has_feed(self, name: str) -> bool:
        return any(feed["name"] == name for feed in self.feeds)

    def load_feed_data(self, name: str, key: str) -> pd.DataFrame:
        """Fetch a feed and return the named section as a DataFrame."""
        feed_url = self.get_feed_url(name)
        sources = requests.get(feed_url, timeout=self.timeout).json()
        return pd.DataFrame(sources["data"][key])

    # --- normalized views -------------------------------------------------

    def vehicle_types(self) -> pd.DataFrame:
        """
        The ``vehicle_types`` feed, or an empty frame when unpublished.

        Cached: it changes far more slowly than the hourly status feeds.
        """
        if self._vehicle_types is not None:
            return self._vehicle_types
        columns = [
            "vehicle_type_id",
            "form_factor",
            "propulsion_type",
            "max_range_meters",
        ]
        if not self.has_feed("vehicle_types"):
            self._vehicle_types = pd.DataFrame(columns=columns)
            return self._vehicle_types
        df = self.load_feed_data("vehicle_types", "vehicle_types")
        for column in ("form_factor", "propulsion_type", "max_range_meters"):
            if column not in df.columns:
                df[column] = None
        df["vehicle_type_id"] = df["vehicle_type_id"].astype(str)
        self._vehicle_types = df[columns]
        return self._vehicle_types

    def electric_type_ids(self) -> set[str]:
        """Vehicle type ids whose propulsion is electric."""
        types = self.vehicle_types()
        if types.empty:
            return set()
        electric = types[
            types["propulsion_type"].astype(str).isin(ELECTRIC_PROPULSION)
        ]
        return set(electric["vehicle_type_id"].astype(str))


def count_electric(
    vehicle_types_available: Any, electric_ids: Iterable[str]
) -> int | None:
    """
    Electric count from a GBFS ``vehicle_types_available`` array.

    Returns ``None`` when the field is absent, so callers can fall back to a
    publisher extension rather than recording a spurious zero.
    """
    if not isinstance(vehicle_types_available, (list, tuple)):
        return None
    electric = set(electric_ids)
    total = 0
    for entry in vehicle_types_available:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("vehicle_type_id")) in electric:
            total += int(entry.get("count") or 0)
    return total
