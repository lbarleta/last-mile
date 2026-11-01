"""
The Parquet lake: layout, key enforcement, and the guarantees above them.

Parquet has no primary keys, so everything the old MySQL schema got from
``INSERT IGNORE`` and ``ON DUPLICATE KEY UPDATE`` now lives in
:class:`lastmile.db.Db`. These are the tests for it.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from lastmile import db
from lastmile.db import schema

STATUS_COLUMNS = ("station_id", "ts", "num_vehicles_available", "num_docks_available")


def status_row(station: str, hour: str, bikes: int = 1, docks: int = 9):
    return (station, db.to_dt(hour), bikes, docks)


# --- layout ----------------------------------------------------------------


def test_create_all_lays_out_every_declared_table(lake):
    for name in schema.TABLE_NAMES:
        assert lake.has_table(name)
        assert (lake.dataset_dir(name) / db.SEED_FILE).is_file()


def test_empty_table_is_queryable_with_its_declared_columns(lake):
    assert lake.count("station_status") == 0
    assert lake.columns("station_status") == set(
        schema.table("station_status").column_names
    )
    assert lake.read_sql("SELECT * FROM station_status").empty


def test_reads_work_before_the_lake_exists(tmp_path):
    """
    A dashboard started against an uncollected lake shows nothing, not a crash.

    The view stands in as an empty typed relation until files appear.
    """
    conn = db.Db(tmp_path / "never-created")
    assert conn.count("station_status") == 0
    assert conn.read_sql("SELECT * FROM station_information").empty
    assert schema.missing_tables(conn) == list(schema.TABLE_NAMES)
    conn.close()


def test_handle_opened_before_init_sees_later_writes(tmp_path):
    """A long-lived dashboard process must not need a restart after init-db."""
    reader = db.Db(tmp_path / "lake")
    writer = db.Db(tmp_path / "lake")
    schema.create_all(writer)
    writer.insert_ignore(
        "station_status", STATUS_COLUMNS, [status_row("a", "2026-10-29-08:00")]
    )
    assert reader.count("station_status") == 1
    reader.close()
    writer.close()


def test_history_is_partitioned_by_day(lake):
    lake.insert_ignore(
        "station_status",
        STATUS_COLUMNS,
        [
            status_row("a", "2026-10-28-23:00"),
            status_row("a", "2026-10-29-00:00"),
            status_row("b", "2026-10-29-00:00"),
        ],
    )
    files = {path.name for path in lake._data_files("station_status")}
    assert files == {"2026-10-28.parquet", "2026-10-29.parquet"}
    assert lake.count("station_status") == 3


def test_reference_data_stays_in_one_file(lake):
    lake.upsert("station_information", ("station_id", "name"), [("a", "First")])
    assert [p.name for p in lake._data_files("station_information")] == ["data.parquet"]


def test_files_carry_the_full_declared_header(lake):
    """
    Every file holds every column, so the view needs no schema reconciliation.

    A write that leaves columns out writes them as typed NULLs rather than
    producing a narrower file.
    """
    lake.upsert("station_information", ("station_id", "name"), [("a", "First")])
    frame = lake.read_sql("SELECT * FROM station_information")
    assert list(frame.columns) == list(schema.table("station_information").column_names)
    assert frame.loc[0, "capacity"] is None or frame["capacity"].isna().all()


# --- keys ------------------------------------------------------------------


def test_insert_ignore_is_idempotent(lake):
    rows = [status_row("a", "2026-10-29-08:00"), status_row("b", "2026-10-29-08:00")]
    assert lake.insert_ignore("station_status", STATUS_COLUMNS, rows) == 2
    # Re-running the collector for a stored hour adds nothing, which is what
    # makes a cron entry safe to retry.
    assert lake.insert_ignore("station_status", STATUS_COLUMNS, rows) == 0
    assert lake.count("station_status") == 2


def test_insert_ignore_keeps_the_stored_row(lake):
    hour = "2026-10-29-08:00"
    lake.insert_ignore("station_status", STATUS_COLUMNS, [status_row("a", hour, 5)])
    lake.insert_ignore("station_status", STATUS_COLUMNS, [status_row("a", hour, 99)])
    row = lake.fetchone("SELECT num_vehicles_available FROM station_status")
    assert row[0] == 5


def test_insert_ignore_adds_only_the_new_rows(lake):
    hour = "2026-10-29-08:00"
    lake.insert_ignore("station_status", STATUS_COLUMNS, [status_row("a", hour)])
    added = lake.insert_ignore(
        "station_status",
        STATUS_COLUMNS,
        [status_row("a", hour), status_row("b", hour)],
    )
    assert added == 1
    assert lake.count("station_status") == 2


def test_insert_ignore_dedupes_within_one_batch(lake):
    hour = "2026-10-29-08:00"
    added = lake.insert_ignore(
        "station_status",
        STATUS_COLUMNS,
        [status_row("a", hour, 5), status_row("a", hour, 7)],
    )
    assert added == 1
    assert lake.fetchone("SELECT num_vehicles_available FROM station_status")[0] == 5


def test_upsert_replaces_the_stored_row(lake):
    lake.upsert("station_information", ("station_id", "name"), [("a", "First")])
    lake.upsert("station_information", ("station_id", "name"), [("a", "Renamed")])
    assert lake.count("station_information") == 1
    assert lake.fetchone("SELECT name FROM station_information")[0] == "Renamed"


def test_upsert_leaves_other_rows_alone(lake):
    lake.upsert(
        "station_information", ("station_id", "name"), [("a", "First"), ("b", "Second")]
    )
    lake.upsert("station_information", ("station_id", "name"), [("b", "Renamed")])
    names = dict(lake.fetchall("SELECT station_id, name FROM station_information"))
    assert names == {"a": "First", "b": "Renamed"}


def test_upsert_rejects_a_key_the_table_does_not_have(lake):
    with pytest.raises(ValueError, match="keyed on"):
        lake.upsert(
            "station_information",
            ("station_id", "name"),
            [("a", "First")],
            conflict=["name"],
        )


def test_writing_an_undeclared_column_fails_loudly(lake):
    with pytest.raises(KeyError, match="num_scooters"):
        lake.insert_ignore(
            "station_status",
            ("station_id", "ts", "num_scooters"),
            [("a", db.to_dt("2026-10-29-08:00"), 1)],
        )


def test_partitioned_write_requires_its_timestamp(lake):
    with pytest.raises(ValueError, match="partitioned on ts"):
        lake.insert_ignore("station_status", ("station_id",), [("a",)])


def test_writing_nothing_is_a_no_op(lake):
    assert lake.insert_ignore("station_status", STATUS_COLUMNS, []) == 0
    assert lake.count("station_status") == 0


def test_missing_values_become_null_not_nan(lake):
    import numpy as np

    lake.insert_ignore(
        "station_status",
        STATUS_COLUMNS,
        [("a", db.to_dt("2026-10-29-08:00"), None, np.nan)],
    )
    row = lake.fetchone(
        "SELECT num_vehicles_available, num_docks_available FROM station_status"
    )
    assert row == (None, None)


# --- deletes ---------------------------------------------------------------


def test_delete_removes_matching_rows(lake):
    lake.insert_ignore(
        "station_status",
        STATUS_COLUMNS,
        [status_row("a", "2026-10-28-08:00"), status_row("a", "2026-10-29-08:00")],
    )
    removed = lake.delete("station_status", "ts = ?", (db.to_dt("2026-10-28-08:00"),))
    assert removed == 1
    assert lake.count("station_status") == 1


def test_emptied_partition_file_is_removed(lake):
    lake.insert_ignore(
        "station_status", STATUS_COLUMNS, [status_row("a", "2026-10-29-08:00")]
    )
    lake.delete("station_status", "station_id = ?", ("a",))
    assert lake._data_files("station_status") == []
    assert lake.count("station_status") == 0


def test_delete_on_an_absent_table_is_a_no_op(tmp_path):
    conn = db.Db(tmp_path / "lake")
    assert conn.delete("station_status", "station_id = ?", ("a",)) == 0
    conn.close()


# --- tracked tables --------------------------------------------------------


OBSERVED = datetime(2026, 10, 29, 8)
LATER = datetime(2026, 10, 30, 8)
REGIONS = ("region_id", "name")


def test_sync_records_the_current_state(lake):
    tally = lake.sync("system_regions", REGIONS, [("a", "Alpha")], OBSERVED)
    assert tally == {"added": 1, "changed": 0, "removed": 0, "total": 1}
    assert lake.fetchall("SELECT region_id, name FROM system_regions") == [
        ("a", "Alpha")
    ]


def test_sync_logs_nothing_when_nothing_changed(lake):
    """
    The reason tracked tables exist: an hourly refresh of data that changes
    twice a year must not write a row an hour.
    """
    rows = [("a", "Alpha"), ("b", "Bravo")]
    lake.sync("system_regions", REGIONS, rows, OBSERVED)
    tally = lake.sync("system_regions", REGIONS, rows, LATER)
    assert tally == {"added": 0, "changed": 0, "removed": 0, "total": 2}
    assert lake.count("system_regions_log") == 2  # the two original adds


def test_sync_logs_additions_changes_and_removals(lake):
    lake.sync("system_regions", REGIONS, [("a", "Alpha"), ("b", "Bravo")], OBSERVED)
    tally = lake.sync(
        "system_regions", REGIONS, [("a", "Renamed"), ("c", "Charlie")], LATER
    )
    assert tally == {"added": 1, "changed": 1, "removed": 1, "total": 2}

    log = lake.read_sql(
        "SELECT region_id, name, change FROM system_regions_log "
        "WHERE observed_at = ? ORDER BY region_id",
        (LATER,),
    )
    assert list(log.itertuples(index=False, name=None)) == [
        ("a", "Renamed", "changed"),
        # A removal keeps the last values seen, so the log reads on its own.
        ("b", "Bravo", "removed"),
        ("c", "Charlie", "added"),
    ]


def test_sync_removes_entities_from_the_current_state(lake):
    lake.sync("system_regions", REGIONS, [("a", "Alpha"), ("b", "Bravo")], OBSERVED)
    lake.sync("system_regions", REGIONS, [("a", "Alpha")], LATER)
    assert lake.fetchall("SELECT region_id FROM system_regions") == [("a",)]


def test_a_null_becoming_a_value_counts_as_a_change(lake):
    lake.sync("system_regions", REGIONS, [("a", None)], OBSERVED)
    tally = lake.sync("system_regions", REGIONS, [("a", "Alpha")], LATER)
    assert tally["changed"] == 1


def test_an_empty_feed_does_not_wipe_the_table(lake):
    """
    A feed that briefly returns nothing is an outage, not a mass removal.

    Treating it as one would log every station as removed and then re-added.
    """
    lake.sync("system_regions", REGIONS, [("a", "Alpha")], OBSERVED)
    tally = lake.sync("system_regions", REGIONS, [], LATER)
    assert tally == {"added": 0, "changed": 0, "removed": 0, "total": 1}
    assert lake.count("system_regions") == 1
    assert lake.count("system_regions_log") == 1


def test_sync_rejects_an_untracked_table(lake):
    with pytest.raises(ValueError, match="not a tracked table"):
        lake.sync("station_status", STATUS_COLUMNS, [], OBSERVED)


# --- timestamps ------------------------------------------------------------


def test_snapshot_keys_round_trip(lake):
    hour = "2026-10-29-08:00"
    lake.insert_ignore("station_status", STATUS_COLUMNS, [status_row("a", hour)])
    stored = lake.fetchone("SELECT ts FROM station_status")[0]
    assert isinstance(stored, datetime)
    assert db.to_key(stored) == hour


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        (db.key_expr, "2026-10-29-08:00"),
        (db.date_expr, "2026-10-29"),
        (db.hour_expr, "08"),
        (db.hour_label_expr, "08:00"),
    ],
)
def test_sql_fragments(lake, fragment, expected):
    lake.insert_ignore(
        "station_status", STATUS_COLUMNS, [status_row("a", "2026-10-29-08:00")]
    )
    assert lake.fetchone(f"SELECT {fragment('ts')} FROM station_status")[0] == expected


def test_real_cast_does_not_truncate(lake):
    lake.insert_ignore(
        "station_status", STATUS_COLUMNS, [status_row("a", "2026-10-29-08:00", 1, 3)]
    )
    expression = f"{db.real_cast('num_vehicles_available')} / 4"
    assert lake.fetchone(f"SELECT {expression} FROM station_status")[0] == 0.25
