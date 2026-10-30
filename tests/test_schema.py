"""The schema declaration's own invariants."""

from __future__ import annotations

import pytest

from lastmile.db import schema


def test_every_table_is_reachable_by_name():
    assert set(schema.TABLE_NAMES) == {t.name for t in schema.TABLES}
    for name in schema.TABLE_NAMES:
        assert schema.table(name).name == name


def test_unknown_table_names_what_exists():
    with pytest.raises(KeyError, match="station_status"):
        schema.table("stations_status")


def test_keys_and_partitions_are_declared_columns():
    for spec in schema.TABLES:
        declared = set(spec.column_names)
        assert set(spec.key) <= declared
        if spec.partition_by:
            assert spec.partition_by in declared


def test_a_partitioned_table_must_be_keyed_on_its_partition():
    """
    Otherwise a row could move between files and leave its old copy behind.

    Keys are applied one file at a time, so the merge would never open the
    file holding the stale row.
    """
    with pytest.raises(ValueError, match="part of its key"):
        schema.Table(
            "drifting",
            (("id", "VARCHAR"), ("ts", "TIMESTAMP")),
            key=("id",),
            partition_by="ts",
        )


def test_every_tracked_table_gets_a_change_log():
    for name in schema.TRACKED_TABLES:
        spec = schema.table(name)
        log = schema.table(spec.log_name)
        # Same columns, plus when the change was seen and what kind it was.
        assert log.column_names == (*spec.column_names, "observed_at", "change")
        assert log.key == (*spec.key, "observed_at")
        # A log is not itself tracked; that would recurse.
        assert not log.tracked


def test_table_groups_are_disjoint_and_cover_the_declarations():
    logs = {schema.table(name).log_name for name in schema.TRACKED_TABLES}
    grouped = {*schema.TRACKED_TABLES, *schema.HOURLY_TABLES, *logs}
    # `weather` is the one table in no group: not GBFS, no history. Geofencing
    # is in the lake but not in a table at all — see lastmile.geofencing.
    assert set(schema.TABLE_NAMES) - grouped == {"weather"}
    assert not set(schema.TRACKED_TABLES) & set(schema.HOURLY_TABLES)
    assert not any(name.startswith("geofencing") for name in schema.TABLE_NAMES)


def test_no_forecast_tables_remain():
    """Forecasting is a stub; the warehouse holds nothing for it."""
    assert not [n for n in schema.TABLE_NAMES if n.startswith("forecast")]


def test_hourly_tables_are_partitioned_and_keyed_on_ts():
    for name in schema.HOURLY_TABLES:
        spec = schema.table(name)
        assert spec.partition_by == "ts"
        assert "ts" in spec.key
