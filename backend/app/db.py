"""Thin database layer: PostgreSQL in production (psycopg 3), SQLite for quick local runs.

Queries are written once in Postgres style (%s placeholders, ::jsonb casts) and
translated for SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

JSON_COLUMNS = {"headers", "mapping", "raw", "mapped", "errors", "warnings", "merged_from"}

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_jobs (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    object_name     TEXT NOT NULL DEFAULT 'Lead',
    status          TEXT NOT NULL DEFAULT 'uploaded',
    headers         JSONB NOT NULL DEFAULT '[]',
    mapping         JSONB,
    total_rows      INTEGER NOT NULL DEFAULT 0,
    valid_rows      INTEGER NOT NULL DEFAULT 0,
    invalid_rows    INTEGER NOT NULL DEFAULT 0,
    duplicate_rows  INTEGER NOT NULL DEFAULT 0,
    created_rows    INTEGER NOT NULL DEFAULT 0,
    updated_rows    INTEGER NOT NULL DEFAULT 0,
    failed_rows     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_at       TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS staged_records (
    id            SERIAL PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    row_number    INTEGER NOT NULL,
    raw           JSONB NOT NULL,
    mapped        JSONB,
    status        TEXT NOT NULL DEFAULT 'pending',
    errors        JSONB NOT NULL DEFAULT '[]',
    warnings      JSONB NOT NULL DEFAULT '[]',
    dedupe_key    TEXT,
    duplicate_of  INTEGER,
    merged_from   JSONB NOT NULL DEFAULT '[]',
    sf_id         TEXT,
    sf_action     TEXT,
    sf_error      TEXT,
    UNIQUE (job_id, row_number)
);
CREATE INDEX IF NOT EXISTS idx_staged_records_job_status ON staged_records(job_id, status);
"""

SQLITE_SCHEMA = (
    POSTGRES_SCHEMA.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    .replace("JSONB", "TEXT")
    .replace("TIMESTAMPTZ", "TEXT")
)


class Database:
    def __init__(self, url: str):
        self.url = url
        self.kind = "sqlite" if url.startswith("sqlite") else "postgres"
        if self.kind == "sqlite":
            self._path = url.split("sqlite:///", 1)[-1] or ":memory:"
            self._memory_conn = (
                sqlite3.connect(":memory:", check_same_thread=False) if self._path == ":memory:" else None
            )

    # -- connections -------------------------------------------------------------------
    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.kind == "postgres":
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self.url, row_factory=dict_row) as conn:
                yield conn
        else:
            conn = self._memory_conn or sqlite3.connect(self._path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._memory_conn is None:
                    conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            if self.kind == "postgres":
                conn.execute(POSTGRES_SCHEMA)
            else:
                conn.executescript(SQLITE_SCHEMA)

    # -- helpers -----------------------------------------------------------------------
    def _sql(self, sql: str) -> str:
        if self.kind == "sqlite":
            return sql.replace("::jsonb", "").replace("%s", "?")
        return sql

    @staticmethod
    def _row(row: Any) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k, v in d.items():
            if k in JSON_COLUMNS and isinstance(v, str):
                d[k] = json.loads(v)
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        with self.connect() as conn:
            return self._row(conn.execute(self._sql(sql), params).fetchone())

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.connect() as conn:
            return [self._row(r) for r in conn.execute(self._sql(sql), params).fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.connect() as conn:
            conn.execute(self._sql(sql), params)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        if not rows:
            return
        with self.connect() as conn:
            if self.kind == "postgres":
                with conn.cursor() as cur:
                    cur.executemany(sql, rows)
            else:
                conn.executemany(self._sql(sql), rows)


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)
