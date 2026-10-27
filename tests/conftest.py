"""
Shared fixtures. No tests exist yet; this is the wiring for them.

Unit tests should build small frames and call the metric/collect functions
directly. Tests that need a database get ``db`` below, which connects to
``LASTMILE_TEST_DATABASE_URL`` and is skipped when that is not set, so the
suite never touches a production warehouse by accident.
"""

from __future__ import annotations

import os

import pytest

from lastmile import settings


@pytest.fixture(autouse=True)
def fresh_settings():
    """Each test reads settings cold, so monkeypatched env vars take effect."""
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


@pytest.fixture
def db():
    """A connection to the dedicated test database, skipped when unset."""
    url = os.environ.get("LASTMILE_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("LASTMILE_TEST_DATABASE_URL is not set")
    from lastmile import db as db_mod

    conn = db_mod.connect(url)
    yield conn
    conn.close()
