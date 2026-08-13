"""
GBFS feed client and shared database handle.

Feed parsing normalizes the places where GBFS publishers disagree, so the rest
of the package sees one consistent shape:

* ``num_ebikes_available`` is a Lyft extension, not part of GBFS. The spec way
  to count electric bikes is ``vehicle_types_available`` cross-referenced with
  the ``vehicle_types`` feed, which is what this reads when it is available.
* ``vehicle_type_id`` is kept as text. Lyft happens to publish ``"1"``/``"2"``
  but Spin and Bird publish UUIDs.
* ``is_reserved`` / ``is_disabled`` arrive as integers from Lyft and as real
  booleans from Spin, and are coerced to 0/1 either way.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import pandas as pd
import requests

from .engine import Db, as_url, make_engine

REQUEST_TIMEOUT = 30

# GBFS propulsion types that count as an "e-bike" for the dashboard's purposes.
ELECTRIC_PROPULSION = {"electric", "electric_assist"}


def as_int_flag(value: Any) -> Optional[int]:
    """GBFS publishers use both 0/1 and true/false for these flags."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class LastMileUtils:
    """Feed access plus a connection to the configured database."""

    def __init__(
        self,
        feeds_url: str,
        lang: str = "en",
        db_path: Optional[str] = None,
    ):
        """
        Args:
            feeds_url: URL of the GBFS discovery document.
            lang: Feed language code.
            db_path: MySQL URL. Defaults to ``LASTMILE_DATABASE_URL``.
        """
        self.db_path = db_path
        self.url = as_url(db_path)
        self.engine = make_engine(self.url)
        self.conn = Db(self.engine.connect())
        self.feeds_url = feeds_url
        self.lang = lang
        self.feeds = self.get_system_feeds()
        self._vehicle_types: Optional[pd.DataFrame] = None

    def __enter__(self) -> "LastMileUtils":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False

    # --- feeds ------------------------------------------------------------

    def get_system_feeds(self) -> list[Dict[str, Any]]:
        """Feed list from the GBFS discovery document."""
        try:
            sources = requests.get(self.feeds_url, timeout=REQUEST_TIMEOUT).json()
        except Exception as exc:
            print(f"Error fetching system feeds: {exc}")
            raise
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
        try:
            sources = requests.get(feed_url, timeout=REQUEST_TIMEOUT).json()
            return pd.DataFrame(sources["data"][key])
        except requests.RequestException as exc:
            print(f"Error fetching data from {feed_url}: {exc}")
            raise
        except KeyError as exc:
            print(f"Error parsing JSON data: {exc}")
            raise

    # --- normalized views -------------------------------------------------

    def vehicle_types(self) -> pd.DataFrame:
        """
        The ``vehicle_types`` feed, or an empty frame when unpublished.

        Cached: it changes far more slowly than the hourly status feeds.
        """
        if self._vehicle_types is not None:
            return self._vehicle_types
        if not self.has_feed("vehicle_types"):
            self._vehicle_types = pd.DataFrame(
                columns=[
                    "vehicle_type_id",
                    "form_factor",
                    "propulsion_type",
                    "max_range_meters",
                ]
            )
            return self._vehicle_types
        df = self.load_feed_data("vehicle_types", "vehicle_types")
        for column in ("form_factor", "propulsion_type", "max_range_meters"):
            if column not in df.columns:
                df[column] = None
        df["vehicle_type_id"] = df["vehicle_type_id"].astype(str)
        self._vehicle_types = df[
            ["vehicle_type_id", "form_factor", "propulsion_type", "max_range_meters"]
        ]
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

    # --- database ---------------------------------------------------------

    def connect(self) -> Db:
        if self.conn is None:
            self.conn = Db(self.engine.connect())
        return self.conn

    def disconnect(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def count_electric(
    vehicle_types_available: Any, electric_ids: Iterable[str]
) -> Optional[int]:
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
