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
import os
from pathlib import Path

import pytest

from lastmile import settings

FIXTURES = Path(__file__).parent / "fixtures" / "gbfs"


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch, tmp_path):
    """
    Each test reads settings cold, with nothing inherited from the host.

    The repo's own lastmile.toml and .env would otherwise leak in — pointing
    tests at a real lake, or at whichever feed the developer last collected.
    Settings also read ``.env`` from the working directory, so run from tmp.
    """
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith(f"{settings.ENV_PREFIX}_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(f"{settings.ENV_PREFIX}_CONFIG", str(_empty_config(tmp_path)))
    monkeypatch.setenv(f"{settings.ENV_PREFIX}_LAKE_PATH", str(tmp_path / "lake"))
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def _empty_config(tmp_path: Path) -> Path:
    path = tmp_path / "lastmile.toml"
    path.write_text("", encoding="utf-8")
    return path


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
