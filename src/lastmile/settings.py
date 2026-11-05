"""
Runtime configuration.

Three layers, each overriding the one before it:

1. The field defaults on :class:`Settings` — what the code does with no
   configuration at all.
2. ``lastmile.toml``, found at or above the working directory (or wherever
   ``LASTMILE_CONFIG`` points). This is where tunables live: search radii,
   thresholds, feed URLs.
3. Environment variables, including anything in a ``.env`` file. Use these for
   deployment-specific values you would rather not commit — paths, analytics
   ids, a feed URL that differs per host.

Keys are flat: the TOML key and the ``Settings`` field share a name, and the
environment variable is that name uppercased with a ``LASTMILE_`` prefix, so
``lake_path`` is ``LASTMILE_LAKE_PATH`` and ``coverage_radius_m`` is
``LASTMILE_COVERAGE_RADIUS_M``. Strings are coerced to the type of the default;
lists are comma-separated in the environment.

Nothing deployment-specific is stored in this file: installing the package never
means editing its source.
"""

from __future__ import annotations

import os
import tomllib
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "lastmile.toml"
ENV_FILENAME = ".env"
ENV_PREFIX = "LASTMILE"


@dataclass(frozen=True)
class Settings:
    """Every tunable, plus the directory relative paths resolve against."""

    # The directory holding lastmile.toml (or the cwd when there is none).
    root: Path = Path(".")

    # --- warehouse ----------------------------------------------------------
    # Directory holding the Parquet data lake, relative to this file's
    # directory unless absolute. Nothing else is needed to run: no server, no
    # credentials, and the whole warehouse moves by copying this directory.
    lake_path: str = "data/lake"

    # --- GBFS feed ----------------------------------------------------------
    # A GBFS discovery document (gbfs.json) for any system, 2.3 or 3.x.
    feeds_url: str = "https://austin.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json"
    feeds_lang: str = "en"
    # The zone snapshot hours are shown in. Blank reads the system's own
    # timezone from its system_information feed, which is where a feed-agnostic
    # deployment should get it. Display only: the lake itself stores instants.
    timezone: str = ""
    request_timeout_s: int = 30

    # --- metrics ------------------------------------------------------------
    # Ops "day" window for problematic-station scoring (local hour, inclusive).
    ops_day_hour_start: int = 7
    ops_day_hour_end: int = 20
    problematic_lookback_hours: int = 3
    # Nearest non-problematic alternative for rebalancing suggestions
    backup_station_radius_m: int = 900
    # Free-floating e-bikes at or below this remaining range count as low-range
    low_range_meters: int = 5000
    # A station holding bikes and docks but below this bike share counts as "low"
    low_station_bike_share: float = 0.2
    # Trailing window for the "typical for this hour" supply-balance baseline.
    supply_baseline_days: int = 28
    # Overnight hours used to estimate fleet size, when nearly all bikes are parked.
    fleet_baseline_hours: tuple[int, ...] = (0, 1, 2, 3, 4)

    # --- walk-shed coverage ---------------------------------------------------
    coverage_radius_m: int = 300
    # Relative paths resolve against the directory holding lastmile.toml.
    boundary_geojson: str = "assets/sf_county_boundary.geojson"
    # California State Plane Zone III (meters) — good for SF buffering
    projected_crs: str = "EPSG:3310"

    # --- dashboard ------------------------------------------------------------
    dashboard_title: str = "Last Mile"
    # Optional Umami analytics; set LASTMILE_UMAMI_WEBSITE_ID in .env
    umami_website_id: str = ""

    def path(self, value: str) -> Path:
        """Resolve a configured path against the project root."""
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def lake_dir(self) -> Path:
        return self.path(self.lake_path)

    @property
    def boundary_geojson_path(self) -> Path:
        return self.path(self.boundary_geojson)


# --- loading --------------------------------------------------------------


def load_dotenv(path: Path) -> None:
    """
    Load ``KEY=VALUE`` pairs from a .env file, never overriding real
    environment variables.

    Values may be quoted. Use single quotes for anything containing a ``$``,
    such as a database name on a shared host: this parser leaves it alone, but
    a shell that ``source``s the same file would expand it.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("'").strip('"'))


def find_config(start: Path | None = None) -> Path | None:
    """
    Locate ``lastmile.toml``: ``LASTMILE_CONFIG`` if set, else the nearest one
    at or above the working directory. Returns None when there is none, in which
    case the defaults on :class:`Settings` apply.
    """
    override = os.environ.get(f"{ENV_PREFIX}_CONFIG", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"{ENV_PREFIX}_CONFIG points at {path}, which does not exist"
            )
        return path
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _coerce(raw: Any, default: Any) -> Any:
    """Cast a TOML or environment value to the type of the field's default."""
    if isinstance(default, tuple):
        items = raw.split(",") if isinstance(raw, str) else list(raw)
        sample = default[0] if default else ""
        return tuple(
            _coerce(item.strip() if isinstance(item, str) else item, sample)
            for item in items
            if not (isinstance(item, str) and not item.strip())
        )
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return str(raw)


def load_settings(path: str | Path | None = None) -> Settings:
    """Read configuration from disk. Prefer :func:`get_settings`."""
    config_path = Path(path).expanduser().resolve() if path else find_config()
    root = config_path.parent if config_path else Path.cwd().resolve()

    # Before any override is read, and cwd first so running from elsewhere in
    # the tree still picks up a local .env.
    load_dotenv(Path.cwd() / ENV_FILENAME)
    load_dotenv(root / ENV_FILENAME)

    data: Mapping[str, Any] = {}
    if config_path:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)

    known = {f.name: f.default for f in fields(Settings) if f.name != "root"}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(
            f"unknown key(s) in {config_path}: {', '.join(sorted(unknown))}"
        )

    # Keys that no longer exist are more often a stale .env than a typo, and
    # either way silently ignoring them would hide the problem.
    stale = sorted(
        name
        for name in os.environ
        if name.startswith(f"{ENV_PREFIX}_")
        and name != f"{ENV_PREFIX}_CONFIG"
        and name.removeprefix(f"{ENV_PREFIX}_").lower() not in known
    )
    if stale:
        warnings.warn(
            f"ignoring unknown setting(s) in the environment: {', '.join(stale)}",
            stacklevel=2,
        )

    values: dict[str, Any] = {"root": root}
    for name, default in known.items():
        env_value = os.environ.get(f"{ENV_PREFIX}_{name}".upper())
        raw = env_value.strip() if env_value is not None else data.get(name)
        if raw is None:
            continue
        try:
            values[name] = _coerce(raw, default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad value for {name}: {raw!r} ({exc})") from exc
    return Settings(**values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, loaded once."""
    return load_settings()


def reload_settings() -> Settings:
    """Drop the cache and re-read. For tests and the CLI's ``--config``."""
    get_settings.cache_clear()
    return get_settings()
