"""
The warehouse: a Parquet data lake with DuckDB in front of it.

There is no database server and no catalog file. Each table is a directory of
Parquet files under the lake root (see :mod:`lastmile.db.schema` for the
layout), exposed to SQL as a DuckDB view over ``read_parquet``. Deploying is
copying a directory; moving a warehouse between machines is ``rsync``; reading
one without this package is ``duckdb -c "SELECT * FROM 'station_status/*'"``.

DuckDB itself is in-memory and per-process, which is what makes that work:
nothing locks, so the hourly collector can append while the dashboard reads, and
a Streamlit app can hold a handle open for days without a connection pool. Views
re-resolve their glob on every query, so files written after a handle was opened
show up without reconnecting.

Parquet has no primary keys, so :class:`Db` applies the ones
:mod:`lastmile.db.schema` declares on the write path. A write reads the affected
file, merges the new rows against it by key, writes a temporary file and renames
it over the old one. Renames are atomic, so a concurrent reader sees either the
whole old file or the whole new one. That is also what makes collection
idempotent: re-running an hour that is already stored merges to the same bytes.

Three write methods, differing in what happens to rows already stored:
:meth:`Db.insert_ignore` appends, keeping the stored row on a key collision;
:meth:`Db.upsert` appends, replacing it; and :meth:`Db.sync` replaces a tracked
table's whole current state, logging only what actually differed.

Snapshot hours cross this boundary as ``YYYY-MM-DD-HH:00`` strings, which is
what the app, its cache keys, and the metric layer speak. They are bound as real
datetimes and formatted back on the way out, so ``ts`` is a genuine TIMESTAMP
without that leaking upward.

The query layer in :mod:`lastmile.db.queries` is written against the SQL
fragments below rather than spelling DuckDB functions inline, so it stays
readable and portable.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ..constants import TIMESTAMP_FORMAT
from ..settings import get_settings
from . import schema

# Zero-row file carrying the typed header, written when a table is created. It
# is what gives a view over an empty table its column types, and keeps the glob
# from matching nothing (which DuckDB treats as an error).
SEED_FILE = "_schema.parquet"
# Single-file tables keep everything here; partitioned ones use <date>.parquet.
DATA_FILE = "data.parquet"
PARTITION_FORMAT = "%Y-%m-%d"


# --- lake location ---------------------------------------------------------


def resolve_lake_path() -> Path:
    """The configured lake directory, resolved against the project root."""
    return get_settings().lake_dir


def as_path(target: str | Path | None) -> Path:
    """Normalize an explicit ``--lake`` argument, falling back to settings."""
    if target is None or (isinstance(target, str) and not target.strip()):
        return resolve_lake_path()
    return Path(target).expanduser()


def describe(path: str | Path) -> str:
    """A version of the location safe to print. Nothing secret in a path."""
    return str(path)


def connect(path: str | Path | None = None) -> Db:
    """Open a handle to the configured lake, or to an explicit directory."""
    return Db(as_path(path))


# --- timestamp conversion at the storage boundary -------------------------


def to_dt(timestamp: str) -> datetime:
    """Parse a ``YYYY-MM-DD-HH:00`` snapshot key into a datetime."""
    return datetime.strptime(timestamp, TIMESTAMP_FORMAT)


def to_key(value: Any) -> str | None:
    """Format a stored timestamp back into a ``YYYY-MM-DD-HH:00`` key."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime(TIMESTAMP_FORMAT)


def keys_from_series(series: pd.Series) -> pd.Series:
    """Vectorized :func:`to_key` for a DataFrame column."""
    return pd.to_datetime(series, errors="coerce").dt.strftime(TIMESTAMP_FORMAT)


def rows_from_frame(df: pd.DataFrame, columns: Sequence[str]) -> list[tuple]:
    """
    Frame to row tuples, with missing values as None.

    The ``astype(object)`` matters: on a float column ``where(notna, None)``
    writes NaN back rather than None, and NaN is not NULL.
    """
    frame = df.reindex(columns=list(columns)).astype(object)
    frame = frame.where(pd.notna(frame), None)
    return list(frame.itertuples(index=False, name=None))


# --- SQL fragments ---------------------------------------------------------
#
# DuckDB's strftime covers all of these directly, including the literal ':00'
# that an hour label ends with.


def hour_expr(column: str) -> str:
    """Zero-padded local hour, '00'–'23'."""
    return f"strftime({column}, '%H')"


def hour_label_expr(column: str) -> str:
    """An 'HH:00' label for the snapshot picker."""
    return f"strftime({column}, '%H:00')"


def date_expr(column: str) -> str:
    """Local calendar date as 'YYYY-MM-DD'."""
    return f"strftime({column}, '%Y-%m-%d')"


def key_expr(column: str) -> str:
    """The snapshot key in ``YYYY-MM-DD-HH:00`` form."""
    return f"strftime({column}, '{TIMESTAMP_FORMAT}')"


def real_cast(column: str) -> str:
    """Force float division; an integer column would otherwise truncate."""
    return f"CAST({column} AS DOUBLE)"


# --- helpers ---------------------------------------------------------------


def quote(identifier: str) -> str:
    """Quote a table or column name."""
    return '"' + identifier.replace('"', '""') + '"'


def _literal(path: str | Path) -> str:
    """A path as a SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


def _cols(columns: Iterable[str]) -> str:
    return ", ".join(quote(c) for c in columns)


def _scrub(value: Any) -> Any:
    """
    Missing values arrive from pandas as NaN, NaT or NA; Parquet wants NULL.

    Anything that slips through fails at insert time against a typed column,
    with a much less obvious message than this.
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _empty_select(spec: schema.Table) -> str:
    """A zero-row relation carrying the table's full typed header."""
    projection = ", ".join(
        f"CAST(NULL AS {type_}) AS {quote(name)}" for name, type_ in spec.columns
    )
    return f"SELECT {projection} WHERE false"


# --- connection wrapper ----------------------------------------------------


class Db:
    """
    A handle on one lake directory.

    The query layer writes ``?`` placeholders and passes tuples, which is
    DuckDB's own paramstyle, so statements go through unrewritten.

    Every statement runs on its own DuckDB cursor. Cursors share the catalog
    (and therefore the views) but not their result sets, which is what keeps
    concurrent Streamlit sessions from reading each other's rows.
    """

    def __init__(
        self, root: str | Path, *, con: duckdb.DuckDBPyConnection | None = None
    ):
        self.root = Path(root).expanduser()
        self._con = con if con is not None else duckdb.connect()
        # Tables that have no files yet and are standing in with an empty typed
        # view. Re-checked before reads until each one is backed by real files,
        # so a handle opened against an empty lake still sees a later init-db.
        self._placeholders: set[str] = set()
        for name in schema.TABLE_NAMES:
            self._register(name)

    def __enter__(self) -> Db:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Db({str(self.root)!r})"

    # --- layout -----------------------------------------------------------

    def dataset_dir(self, table: str) -> Path:
        """The directory holding one table's Parquet files."""
        return self.root / table

    def _glob(self, table: str) -> str:
        return str(self.dataset_dir(table) / "*.parquet")

    def _data_files(self, table: str) -> list[Path]:
        """Parquet files holding rows, newest partition last. Excludes the seed."""
        directory = self.dataset_dir(table)
        if not directory.is_dir():
            return []
        return sorted(
            path for path in directory.glob("*.parquet") if path.name != SEED_FILE
        )

    def _register(self, table: str) -> None:
        """(Re)point the view for a table at its files, or at an empty header."""
        spec = schema.table(table)
        if self.has_table(table):
            body = (
                f"SELECT * FROM read_parquet({_literal(self._glob(table))}, "
                "union_by_name=true)"
            )
            self._placeholders.discard(table)
        else:
            body = _empty_select(spec)
            self._placeholders.add(table)
        self._con.execute(f"CREATE OR REPLACE VIEW {quote(table)} AS {body}")

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        for table in list(self._placeholders):
            if self.has_table(table):
                self._register(table)
        return self._con.cursor()

    def ensure_table(self, table: str) -> None:
        """Create a table's directory and typed seed file. Idempotent."""
        spec = schema.table(table)
        directory = self.dataset_dir(table)
        directory.mkdir(parents=True, exist_ok=True)
        seed = directory / SEED_FILE
        if not seed.exists():
            self._con.execute(
                f"COPY ({_empty_select(spec)}) TO {_literal(seed)} (FORMAT PARQUET)"
            )
        self._register(table)

    # --- reads ------------------------------------------------------------

    def execute(self, sql: str, params: Sequence[Any] | None = ()):
        return self._cursor().execute(sql, _bind(params))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        if not rows:
            return 0
        self._cursor().executemany(sql, [_bind(row) for row in rows])
        return len(rows)

    def fetchone(self, sql: str, params: Sequence[Any] | None = ()):
        return self._cursor().execute(sql, _bind(params)).fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] | None = ()):
        return self._cursor().execute(sql, _bind(params)).fetchall()

    def read_sql(self, sql: str, params: Sequence[Any] | None = ()) -> pd.DataFrame:
        return self._cursor().execute(sql, _bind(params)).df()

    # --- introspection ----------------------------------------------------

    def has_table(self, table: str) -> bool:
        """True once the table's dataset exists on disk, empty or not."""
        return (self.dataset_dir(table) / SEED_FILE).is_file()

    def columns(self, table: str) -> set[str]:
        """Column names for a table, or an empty set if it does not exist."""
        if not self.has_table(table):
            return set()
        rows = self._cursor().execute(f"DESCRIBE {quote(table)}").fetchall()
        return {row[0] for row in rows}

    def count(self, table: str) -> int:
        """Row count, or 0 when the table is absent."""
        if not self.has_table(table):
            return 0
        row = self._cursor().execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # --- writes -----------------------------------------------------------

    def insert_ignore(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> int:
        """
        Insert rows, skipping any whose key is already stored.

        Returns the number actually added, so the collector can report an hour
        it had already captured as zero new rows rather than a second copy. A
        table with no declared key appends everything.
        """
        return self._store(table, columns, rows, replace=False)

    def upsert(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        conflict: Sequence[str] | None = None,
    ) -> int:
        """
        Insert rows, replacing any stored row with the same key.

        ``conflict`` is accepted for readability at the call site and checked
        against the table's declared key; the key is what the merge uses.
        """
        spec = schema.table(table)
        if conflict is not None and tuple(conflict) != spec.key:
            raise ValueError(f"{table} is keyed on {spec.key}, not {tuple(conflict)}")
        return self._store(table, columns, rows, replace=True)

    def delete(self, table: str, where: str, params: Sequence[Any] = ()) -> int:
        """
        Drop rows matching a condition, rewriting the files that held them.

        Expensive by design — the lake is built for appends — and intended for
        correcting a bad collection run rather than for routine use.
        """
        if not self.has_table(table):
            return 0
        spec = schema.table(table)
        cur = self._cursor()
        removed = 0
        for path in self._data_files(table):
            source = f"read_parquet({_literal(path)})"
            before = cur.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0]
            cur.execute(
                f"CREATE OR REPLACE TEMP TABLE _kept AS "
                f"SELECT * FROM {source} WHERE NOT ({where})",
                _bind(params),
            )
            after = cur.execute("SELECT COUNT(*) FROM _kept").fetchone()[0]
            if after == before:
                continue
            if after == 0 and spec.partition_by:
                # An emptied partition is a file nobody needs to open again.
                path.unlink()
            else:
                self._replace(cur, "SELECT * FROM _kept", path)
            removed += before - after
        cur.execute("DROP TABLE IF EXISTS _kept")
        return removed

    def sync(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        observed_at: datetime,
    ) -> dict[str, int]:
        """
        Replace a tracked table's current state, logging what changed.

        For everything that describes the system rather than its occupancy —
        stations, vehicle types, pricing plans — an hourly copy would be almost
        entirely duplicate rows. This keeps one current row per entity and
        appends to ``<table>_log`` only when an entity appears, changes or
        disappears, so a year of pricing plans is a handful of rows instead of
        nine thousand identical ones.

        An empty batch is a no-op rather than a wipe: a feed that briefly
        returns nothing should not read as "every station was removed".

        Returns counts of added, changed, removed and total current rows.
        """
        spec = schema.table(table)
        if not spec.tracked:
            raise ValueError(f"{table} is not a tracked table")
        tally = {"added": 0, "changed": 0, "removed": 0, "total": self.count(table)}
        if not rows:
            return tally

        self.ensure_table(table)
        self.ensure_table(spec.log_name)
        cur = self._cursor()
        typed = self._stage(cur, spec, columns, rows)

        path = self.dataset_dir(table) / DATA_FILE
        if path.exists():
            current = f"SELECT * FROM read_parquet({_literal(path)})"
            prelude = f"WITH incoming AS ({typed}), current AS ({current})"
            # Joined on the key with ON rather than USING, so both sides keep
            # their own qualified columns and `incoming.*` stays unambiguous.
            on = " AND ".join(
                f"incoming.{quote(c)} = current.{quote(c)}" for c in spec.key
            )
            # Any value column that differs, a NULL on one side included.
            differs = (
                " OR ".join(
                    f"incoming.{quote(c)} IS DISTINCT FROM current.{quote(c)}"
                    for c in spec.value_columns
                )
                or "false"
            )
            changes = {
                schema.ADDED: f"{prelude} SELECT incoming.* FROM incoming "
                f"ANTI JOIN current ON {on}",
                schema.CHANGED: f"{prelude} SELECT incoming.* FROM incoming "
                f"JOIN current ON {on} WHERE {differs}",
                schema.REMOVED: f"{prelude} SELECT current.* FROM current "
                f"ANTI JOIN incoming ON {on}",
            }
        else:
            changes = {schema.ADDED: typed}

        for change, query in changes.items():
            logged = cur.execute(query).fetchall()
            tally[change] = len(logged)
            self._store(
                spec.log_name,
                (*spec.column_names, "observed_at", "change"),
                [(*row, observed_at, change) for row in logged],
                replace=False,
            )

        tally["total"] = self._replace(cur, typed, path)
        cur.execute("DROP TABLE IF EXISTS _incoming")
        self._register(table)
        return tally

    def _stage(
        self,
        cur: duckdb.DuckDBPyConnection,
        spec: schema.Table,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> str:
        """
        Load a batch into a typed temp table; return a SELECT in table order.

        Every file a table owns carries the full declared header in declared
        order, so columns this write left out are staged as typed NULLs.
        """
        columns = list(columns)
        unknown = [c for c in columns if c not in spec.types]
        if unknown:
            raise KeyError(
                f"{spec.name} has no column(s) {', '.join(unknown)}; "
                f"declared columns are {', '.join(spec.column_names)}"
            )
        declaration = ", ".join(f"{quote(c)} {spec.types[c]}" for c in columns)
        cur.execute(f"CREATE OR REPLACE TEMP TABLE _incoming ({declaration})")
        cur.executemany(
            f"INSERT INTO _incoming VALUES ({', '.join('?' * len(columns))})",
            [_bind(row) for row in rows],
        )
        projection = ", ".join(
            quote(name)
            if name in columns
            else f"CAST(NULL AS {type_}) AS {quote(name)}"
            for name, type_ in spec.columns
        )
        return f"SELECT {projection} FROM _incoming"

    def _store(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        replace: bool,
    ) -> int:
        """Merge rows into the files that hold their keys. See the module docstring."""
        if not rows:
            return 0
        spec = schema.table(table)
        if spec.partition_by and spec.partition_by not in columns:
            raise ValueError(
                f"{table} is partitioned on {spec.partition_by}, which the "
                "written rows do not include"
            )
        self.ensure_table(table)

        cur = self._cursor()
        typed = self._stage(cur, spec, columns, rows)
        written = 0
        for path, partition in self._targets(cur, spec, typed):
            written += self._merge(cur, spec, typed, partition, path, replace)
        cur.execute("DROP TABLE IF EXISTS _incoming")
        return len(rows) if replace else written

    def _targets(
        self, cur: duckdb.DuckDBPyConnection, spec: schema.Table, typed: str
    ) -> list[tuple[Path, str | None]]:
        """The file(s) this batch touches, each with the filter selecting its rows."""
        directory = self.dataset_dir(spec.name)
        if not spec.partition_by:
            return [(directory / DATA_FILE, None)]
        column = quote(spec.partition_by)
        dates = cur.execute(
            f"SELECT DISTINCT strftime({column}, '{PARTITION_FORMAT}') AS d "
            f"FROM ({typed}) ORDER BY d"
        ).fetchall()
        if any(row[0] is None for row in dates):
            raise ValueError(
                f"{spec.name} rows are missing {spec.partition_by}, which names "
                "the file they belong in"
            )
        return [
            (
                directory / f"{date}.parquet",
                f"strftime({column}, '{PARTITION_FORMAT}') = {_literal(date)}",
            )
            for (date,) in dates
        ]

    def _merge(
        self,
        cur: duckdb.DuckDBPyConnection,
        spec: schema.Table,
        typed: str,
        partition: str | None,
        path: Path,
        replace: bool,
    ) -> int:
        """Combine one file with the slice of the batch belonging to it."""
        incoming = (
            typed if partition is None else f"SELECT * FROM ({typed}) WHERE {partition}"
        )
        if spec.key:
            # A batch can repeat a key itself; first row in wins, matching what
            # a row-at-a-time insert against a unique key would have done.
            incoming = (
                f"SELECT * FROM ({incoming}) "
                f"QUALIFY row_number() OVER (PARTITION BY {_cols(spec.key)}) = 1"
            )

        if not path.exists():
            return self._replace(cur, incoming, path)

        existing = f"SELECT * FROM read_parquet({_literal(path)})"
        before = cur.execute(f"SELECT COUNT(*) FROM ({existing})").fetchone()[0]
        prelude = f"WITH incoming AS ({incoming}), existing AS ({existing})"
        if not spec.key:
            body = "SELECT * FROM existing UNION ALL BY NAME SELECT * FROM incoming"
        elif replace:
            body = (
                f"SELECT * FROM existing ANTI JOIN incoming USING ({_cols(spec.key)}) "
                "UNION ALL BY NAME SELECT * FROM incoming"
            )
        else:
            body = (
                "SELECT * FROM existing UNION ALL BY NAME "
                f"SELECT * FROM incoming ANTI JOIN existing USING ({_cols(spec.key)})"
            )
        after = self._replace(cur, f"{prelude} {body}", path)
        return after - before

    def _replace(self, cur: duckdb.DuckDBPyConnection, body: str, path: Path) -> int:
        """
        Write a query's result over a Parquet file, atomically.

        The rename is what readers rely on: a dashboard query running while the
        collector writes opens either the old file or the new one, never a
        half-written one.
        """
        temporary = path.with_name(path.name + ".tmp")
        cur.execute(f"COPY ({body}) TO {_literal(temporary)} (FORMAT PARQUET)")
        rows = cur.execute(
            f"SELECT COUNT(*) FROM read_parquet({_literal(temporary)})"
        ).fetchone()[0]
        os.replace(temporary, path)
        return rows

    def commit(self) -> None:
        """Writes are already durable; each one lands as a file rename."""

    def close(self) -> None:
        self._con.close()


def _bind(params: Sequence[Any] | None) -> list[Any]:
    return [_scrub(value) for value in params] if params else []
