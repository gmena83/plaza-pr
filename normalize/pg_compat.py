"""Postgres (psycopg2) connection wrapper exposing a sqlite3-like interface.

Lets normalize/db.py (and anything using it) run unchanged against Postgres:
- `?` placeholders are converted to %s at execute() time
- rows are dict-like (RealDictCursor) so r["col"] and dict(r) both work
- lastrowid comes from automatically appended RETURNING id on INSERTs
- datetime('now') -> now(), date('now') -> CURRENT_DATE
"""
import re

import psycopg2
import psycopg2.extras


def _translate(sql: str) -> str:
    # date('now') first (contains the datetime prefix pattern in reverse order
    # of length; replacing the longer one first avoids partial collisions)
    sql = sql.replace("datetime('now')", "now()")
    sql = sql.replace("date('now')", "CURRENT_DATE")
    # sqlite's date(col) is a no-op cast for DATE-typed columns in Postgres
    sql = re.sub(r"\bdate\((valid_from|valid_to)\)", r"\1", sql)
    return sql.replace("?", "%s")


class CompatRow(dict):
    """RealDictRow already behaves; kept for clarity."""


class CompatCursor:
    def __init__(self, cur):
        self._cur = cur
        self._lastrowid = None

    def _exec(self, sql, params):
        # psycopg2 RealDictCursor.execute() with an empty tuple breaks on
        # statements without a result set (IndexError); pass None instead.
        self._cur.execute(sql, params if params else None)

    def execute(self, sql, params=None):
        sql_t = _translate(sql)
        # emulate sqlite lastrowid for plain INSERTs (skip conflict-handled inserts:
        # DO NOTHING can return zero rows, and callers there don't use lastrowid)
        if (re.match(r"\s*insert\s+into\s", sql_t, re.I)
                and "returning" not in sql_t.lower()
                and "on conflict" not in sql_t.lower()):
            sql_t = sql_t.rstrip().rstrip(";") + " RETURNING id"
            self._exec(sql_t, params)
            row = self._cur.fetchone() if self._cur.description else None
            self._lastrowid = row["id"] if row else None
        else:
            self._exec(sql_t, params)
        return self

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount


class CompatConnection:
    def __init__(self, dsn: str):
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False

    def execute(self, sql, params=None):
        cur = CompatCursor(self._conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor))
        return cur.execute(sql, params)

    def executescript(self, script: str):
        with self._conn.cursor() as cur:
            cur.execute(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def connect(dsn: str) -> CompatConnection:
    return CompatConnection(dsn)
