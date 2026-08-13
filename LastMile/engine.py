"""
MySQL engine and the thin connection wrapper the query layer uses.

The dashboard runs against a single MySQL database named by
``LASTMILE_DATABASE_URL``. Query modules write ``?`` placeholders and pass tuple
parameters; :class:`Db` rewrites them to the named binds SQLAlchemy expects.

Snapshot hours cross this boundary as ``YYYY-MM-DD-HH:00`` strings, which is
what the app, its cache keys, and the metric layer speak. They are bound as real
datetimes and formatted back on the way out, so the ``ts`` column is a genuine
DATETIME without that leaking upward.
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime
from typing import Any, Optional, Sequence

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

from .config import TIMESTAMP_FORMAT


def resolve_database_url() -> str:
    """The configured connection URL, or raise with how to set one."""
    url = os.environ.get("LASTMILE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "LASTMILE_DATABASE_URL is not set. Point it at your MySQL database, "
            "e.g. mysql://user:password@host/lastmile"
        )
    return normalize_url(url)


def normalize_url(url: str) -> str:
    """Pin PyMySQL onto the bare ``mysql://`` scheme."""
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://") :]
    return url


def as_url(target: Optional[str]) -> str:
    """Normalize a ``--db`` argument, falling back to the environment."""
    return normalize_url(target) if target else resolve_database_url()


def describe(url: str) -> str:
    """A version of the URL safe to print, with any password removed."""
    return url.split("@")[-1] if "@" in url else url


def make_engine(url: Optional[str] = None, **kwargs: Any) -> Engine:
    """Create an engine, defaulting to the configured database."""
    url = normalize_url(url) if url else resolve_database_url()
    # Shared hosts close idle connections and the dashboard sits idle a lot, so
    # recycle below the usual timeout and check liveness before handing one out.
    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("pool_recycle", 280)
    return create_engine(url, **kwargs)


# --- timestamp conversion at the storage boundary -------------------------


def to_dt(timestamp: str) -> datetime:
    """Parse a ``YYYY-MM-DD-HH:00`` snapshot key into a datetime."""
    return datetime.strptime(timestamp, TIMESTAMP_FORMAT)


def to_key(value: Any) -> Optional[str]:
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
    writes NaN back rather than None, and the driver rejects NaN outright.
    """
    frame = df.reindex(columns=list(columns)).astype(object)
    frame = frame.where(pd.notna(frame), None)
    return list(frame.itertuples(index=False, name=None))


# --- SQL fragments --------------------------------------------------------
#
# DATE_FORMAT would be the natural way to write these, but its '%Y'-style codes
# collide with PyMySQL's format paramstyle: a literal '%' in the statement gets
# consumed as a parameter marker. Composing from DATE/HOUR/LPAD/CONCAT keeps the
# SQL free of '%' entirely.


def hour_expr(column: str) -> str:
    """Zero-padded local hour, '00'–'23'."""
    return f"LPAD(HOUR({column}), 2, '0')"


def hour_label_expr(column: str) -> str:
    """An 'HH:00' label for the snapshot picker."""
    return f"CONCAT(LPAD(HOUR({column}), 2, '0'), ':00')"


def date_expr(column: str) -> str:
    """Local calendar date as 'YYYY-MM-DD'."""
    return f"CAST(DATE({column}) AS CHAR)"


def key_expr(column: str) -> str:
    """The snapshot key in ``YYYY-MM-DD-HH:00`` form."""
    return (
        f"CONCAT(CAST(DATE({column}) AS CHAR), '-', "
        f"LPAD(HOUR({column}), 2, '0'), ':00')"
    )


def real_cast(column: str) -> str:
    """
    Force float division; an integer column would otherwise truncate.

    Multiplication rather than CAST(... AS DOUBLE), which only exists in
    MySQL 8.0.17 and later.
    """
    return f"({column} * 1.0)"


# --- connection wrapper ---------------------------------------------------

_PLACEHOLDER = re.compile(r"\?")

# A colon followed by a digit inside a string literal, as in the ':00' that
# closes an hour label. SQLAlchemy's text() would read that as a bind parameter
# named "00" and swap the literal out for a parameter marker. Our own binds are
# always named pN, so a digit can never start a legitimate one here.
_LITERAL_COLON = re.compile(r"(?<!\\):(?=\d)")


def _scrub(value: Any) -> Any:
    """
    Missing values arrive from pandas as NaN or NaT; MySQL wants NULL.

    The driver raises on NaN rather than coercing it, so anything that slips
    through here fails at execute time with a much less obvious message.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    return value


def _params(values: Sequence[Any]) -> dict:
    return {f"p{i}": _scrub(v) for i, v in enumerate(values)}


def _bind(sql: str, params: Sequence[Any] | None):
    """Rewrite ``?`` placeholders into the named binds SQLAlchemy expects."""
    sql = _LITERAL_COLON.sub(r"\\:", sql)
    if not params:
        return text(sql), {}
    values = list(params)
    index = -1

    def _sub(_match: re.Match) -> str:
        nonlocal index
        index += 1
        return f":p{index}"

    bound_sql = _PLACEHOLDER.sub(_sub, sql)
    if index + 1 != len(values):
        raise ValueError(
            f"expected {index + 1} parameters for query, got {len(values)}"
        )
    return text(bound_sql), _params(values)


def _cols(columns: Sequence[str]) -> str:
    return ", ".join(f"`{c}`" for c in columns)


class Db:
    """
    Thin wrapper over a SQLAlchemy connection.

    Exists so the query layer can keep writing ``?`` placeholders and plain
    tuples rather than being rewritten around SQLAlchemy's bind syntax.
    """

    def __init__(self, connection: Connection):
        self._conn = connection

    @property
    def connection(self) -> Connection:
        return self._conn

    def execute(self, sql: str, params: Sequence[Any] | None = ()):
        return self._conn.execute(*_bind(sql, params))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        """Run a statement over many parameter sets; returns rows affected."""
        if not rows:
            return 0
        clause, _ = _bind(sql, rows[0])
        result = self._conn.execute(clause, [_params(row) for row in rows])
        return result.rowcount if result.rowcount is not None else 0

    def fetchone(self, sql: str, params: Sequence[Any] | None = ()):
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] | None = ()):
        return self.execute(sql, params).fetchall()

    def read_sql(self, sql: str, params: Sequence[Any] | None = ()) -> pd.DataFrame:
        clause, bound = _bind(sql, params)
        return pd.read_sql_query(clause, self._conn, params=bound or None)

    def columns(self, table: str) -> set[str]:
        """Column names for a table, or an empty set if it does not exist."""
        inspector = inspect(self._conn)
        if not inspector.has_table(table):
            return set()
        return {col["name"] for col in inspector.get_columns(table)}

    def has_table(self, table: str) -> bool:
        return inspect(self._conn).has_table(table)

    def indexes(self, table: str) -> set[str]:
        inspector = inspect(self._conn)
        if not inspector.has_table(table):
            return set()
        return {ix["name"] for ix in inspector.get_indexes(table)}

    def insert_ignore(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> int:
        """
        Insert rows, skipping any that collide with an existing key.

        Collection is idempotent because of this: re-running the collector for
        an hour that is already stored is a no-op rather than a second copy.
        """
        if not rows:
            return 0
        placeholders = ", ".join("?" * len(columns))
        sql = (
            f"INSERT IGNORE INTO `{table}` ({_cols(columns)}) "
            f"VALUES ({placeholders})"
        )
        return max(self.executemany(sql, rows), 0)

    def upsert(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        conflict: Sequence[str],
    ) -> int:
        """
        Insert rows, overwriting the non-key columns when they already exist.

        MySQL matches on any unique key rather than a named one, so ``conflict``
        only decides which columns are left alone on update.
        """
        if not rows:
            return 0
        placeholders = ", ".join("?" * len(columns))
        keys = set(conflict)
        updatable = [c for c in columns if c not in keys]
        if updatable:
            assignments = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in updatable)
        else:
            # Nothing to change, but the clause is what makes the insert a no-op
            # instead of a duplicate-key error.
            assignments = f"`{conflict[0]}` = `{conflict[0]}`"
        sql = (
            f"INSERT INTO `{table}` ({_cols(columns)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {assignments}"
        )
        return max(self.executemany(sql, rows), 0)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
