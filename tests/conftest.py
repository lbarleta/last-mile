"""
Shared fixtures.

The warehouse is a directory of Parquet files, so tests build a real one in a
tmp directory instead of needing a server — ``lake`` below is the whole setup.
Feed tests run against recorded GBFS documents in ``fixtures/gbfs`` rather than
the network: two directories are the live Austin 2.3 and 3.0 feeds, trimmed to
three stations, and two more are a hand-written free-floating system, which
Austin does not publish. ``gbfs_client`` serves them through the same code path
a real feed takes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lastmile import settings

FIXTURES = Path(__file__).parent / "fixtures" / "gbfs"


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_config(tmp_path: Path, *, general=None, system=None, metrics=None) -> Path:
    """
    Write ``tmp_path/lastmile.toml``: one system, ``test``, whose lake is
    ``tmp_path/lake`` and whose feed resolves to the recorded fixtures by
    name. Keyword tables add or override keys in the matching TOML table.
    """
    tables = {
        "general": {"default_system": "test", **(general or {})},
        "systems.test": {
            "lake_path": str(tmp_path / "lake"),
            "feeds_url": "gbfs.json",
            **(system or {}),
        },
        "metrics": dict(metrics or {}),
    }
    body = "".join(
        f"[{name}]\n" + "".join(f"{k} = {_toml_value(v)}\n" for k, v in keys.items())
        for name, keys in tables.items()
    )
    path = tmp_path / "lastmile.toml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch, tmp_path):
    """
    Each test reads settings cold, from its own config in tmp.

    The repo's own lastmile.toml would otherwise leak in — pointing tests at a
    real lake, or at whichever feed the developer last collected.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(settings.CONFIG_ENV, str(write_config(tmp_path)))
    settings.select_system(None)
    yield
    settings.select_system(None)


@pytest.fixture
def configure(tmp_path):
    """Rewrite this test's config with extra keys and reload settings."""

    def _configure(**tables):
        write_config(tmp_path, **tables)
        return settings.reload_settings()

    return _configure


@pytest.fixture
def seeded(lake):
    """The :mod:`seed` lake: three stations over 48 hours, one free-bike hour."""
    from seed import seed

    seed(lake)
    return lake


@pytest.fixture
def lake(tmp_path):
    """An empty warehouse in a tmp directory, with its datasets laid out."""
    from lastmile import db
    from lastmile.db import schema

    conn = db.Db(tmp_path / "lake")
    schema.create_all(conn)
    yield conn
    conn.close()


class FixtureTransport:
    """
    Stands in for ``requests.get`` against a directory of recorded feeds.

    The discovery documents advertise bare feed names as their URLs, so a
    lookup resolves to ``<directory>/<name>.json`` and the client's own feed
    resolution — including the 2.x/3.x name aliases — is what is under test.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.requested: list[str] = []

    def __call__(self, url, *, timeout=None, **kwargs):
        name = Path(url).name.removesuffix(".json")
        self.requested.append(name)
        path = self.directory / f"{name}.json"
        if not path.is_file():
            raise AssertionError(f"feed {name!r} is not recorded in {self.directory}")
        return _Response(json.loads(path.read_text(encoding="utf-8")))


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


@pytest.fixture
def feed_transport(monkeypatch):
    """Point the GBFS client at one of the recorded feed sets."""

    def _install(feed_set: str) -> FixtureTransport:
        from lastmile import gbfs

        transport = FixtureTransport(FIXTURES / feed_set)
        monkeypatch.setattr(gbfs.requests, "get", transport)
        return transport

    return _install


@pytest.fixture
def gbfs_client(feed_transport):
    """A :class:`GbfsClient` reading one recorded feed set."""

    def _build(feed_set: str):
        from lastmile.gbfs import GbfsClient

        feed_transport(feed_set)
        return GbfsClient(feeds_url="gbfs.json")

    return _build
