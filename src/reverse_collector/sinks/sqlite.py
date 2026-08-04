from __future__ import annotations

import json
import sqlite3
from typing import Any

from reverse_collector.errors import ConfigurationError
from reverse_collector.models import RunSummary, TaskConfig
from reverse_collector.sinks.base import Sink
from reverse_collector.sinks.files import resolve_output_path


class SQLiteSink(Sink):
    name = "sqlite"

    def __init__(self, path: str, *, table: str, key_fields: list[str] | None = None) -> None:
        if not table:
            raise ConfigurationError("sqlite sink requires table")
        self.path_template = path
        self.table = table
        self.key_fields = key_fields or []
        self.connection: sqlite3.Connection | None = None
        self.columns: set[str] = set()
        self.durable_per_batch = bool(self.key_fields)

    async def start(self, task: TaskConfig, summary: RunSummary) -> None:
        path = resolve_output_path(self.path_template, task)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        existing = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (self.table,)
        ).fetchone()
        if existing:
            rows = self.connection.execute(f"PRAGMA table_info({_quote(self.table)})").fetchall()
            self.columns = {row[1] for row in rows}

    async def write(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        assert self.connection is not None
        incoming = {str(key) for record in records for key in record}
        for index, record in enumerate(records):
            missing_keys = [
                field for field in self.key_fields if field not in record or record[field] is None
            ]
            if missing_keys:
                raise ConfigurationError(
                    f"sqlite record {index} is missing key_fields: {', '.join(missing_keys)}"
                )
        if not self.columns:
            columns = sorted(incoming)
            definitions = [f"{_quote(column)} TEXT" for column in columns]
            if self.key_fields:
                definitions.append(
                    "UNIQUE (" + ", ".join(_quote(field) for field in self.key_fields) + ")"
                )
            self.connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_quote(self.table)} ({', '.join(definitions)})"
            )
            self.columns = set(columns)
        for column in sorted(incoming - self.columns):
            self.connection.execute(
                f"ALTER TABLE {_quote(self.table)} ADD COLUMN {_quote(column)} TEXT"
            )
            self.columns.add(column)

        columns = sorted(incoming)
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(_quote(column) for column in columns)
        sql = f"INSERT INTO {_quote(self.table)} ({names}) VALUES ({placeholders})"
        if self.key_fields:
            updates = [column for column in columns if column not in self.key_fields]
            if updates:
                sql += " ON CONFLICT (" + ", ".join(_quote(x) for x in self.key_fields) + ") DO UPDATE SET "
                sql += ", ".join(
                    f"{_quote(column)}=excluded.{_quote(column)}" for column in updates
                )
            else:
                sql += " ON CONFLICT DO NOTHING"
        values = [tuple(_as_text(record.get(column)) for column in columns) for record in records]
        self.connection.executemany(sql, values)

    async def commit_batch(self) -> None:
        if self.connection is not None:
            self.connection.commit()

    async def finish(self) -> None:
        if self.connection is not None:
            self.connection.commit()
            self.connection.close()
            self.connection = None

    async def abort(self) -> None:
        if self.connection is not None:
            self.connection.rollback()
            self.connection.close()
            self.connection = None


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
