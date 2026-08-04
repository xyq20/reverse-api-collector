from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, TextIO

from reverse_collector.errors import ConfigurationError, DataValidationError
from reverse_collector.models import RunSummary, TaskConfig
from reverse_collector.sinks.base import Sink


def resolve_output_path(template: str, task: TaskConfig) -> Path:
    values = {"task": task.name, "plugin": task.plugin, "dataset": task.dataset}
    values.update({key: str(value) for key, value in task.parameters.items()})
    try:
        rendered = template.format_map(_StrictFormat(values))
    except KeyError as exc:
        raise ConfigurationError(f"unknown output path placeholder: {exc.args[0]}") from exc
    return Path(rendered).expanduser().resolve()


class _StrictFormat(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


class _AtomicTextSink(Sink):
    def __init__(self, path: str, *, encoding: str = "utf-8") -> None:
        self.path_template = path
        self.encoding = encoding
        self.path: Path | None = None
        self.temporary: Path | None = None
        self.handle: TextIO | None = None

    async def start(self, task: TaskConfig, summary: RunSummary) -> None:
        self.path = resolve_output_path(self.path_template, task)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.part")
        self.handle = self.temporary.open("w", encoding=self.encoding, newline="")

    async def _flush(self) -> None:
        if self.handle is not None:
            self.handle.flush()
            os.fsync(self.handle.fileno())

    async def finish(self) -> None:
        if self.handle is None or self.path is None or self.temporary is None:
            return
        await self._flush()
        self.handle.close()
        self.handle = None
        os.replace(self.temporary, self.path)

    async def abort(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None
        if self.temporary is not None:
            self.temporary.unlink(missing_ok=True)


class JsonSink(_AtomicTextSink):
    name = "json"

    def __init__(self, path: str, *, indent: int | None = 2) -> None:
        super().__init__(path)
        self.indent = indent
        self._first = True

    async def start(self, task: TaskConfig, summary: RunSummary) -> None:
        await super().start(task, summary)
        assert self.handle is not None
        self.handle.write("[")

    async def write(self, records: list[dict[str, Any]]) -> None:
        assert self.handle is not None
        for record in records:
            if not self._first:
                self.handle.write(",")
            if self.indent is not None:
                self.handle.write("\n")
                payload = json.dumps(record, ensure_ascii=False, indent=self.indent)
            else:
                payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            self.handle.write(payload)
            self._first = False

    async def finish(self) -> None:
        if self.handle is not None:
            if not self._first:
                self.handle.write("\n")
            self.handle.write("]\n")
        await super().finish()


class JsonlSink(_AtomicTextSink):
    name = "jsonl"

    async def write(self, records: list[dict[str, Any]]) -> None:
        assert self.handle is not None
        for record in records:
            self.handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            self.handle.write("\n")


class CsvSink(_AtomicTextSink):
    name = "csv"

    def __init__(
        self,
        path: str,
        *,
        fields: list[str] | None = None,
        excel_bom: bool = True,
    ) -> None:
        super().__init__(path, encoding="utf-8-sig" if excel_bom else "utf-8")
        self.fields = fields or []
        self.writer: csv.DictWriter[str] | None = None

    async def write(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        assert self.handle is not None
        if self.writer is None:
            self.fields = self.fields or list(records[0])
            self.writer = csv.DictWriter(self.handle, fieldnames=self.fields, extrasaction="raise")
            self.writer.writeheader()
        for record in records:
            nested = {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                for key, value in record.items()
            }
            try:
                self.writer.writerow(nested)
            except ValueError as exc:
                raise DataValidationError(str(exc)) from exc


class StdoutSink(Sink):
    name = "stdout"
    durable_per_batch = True

    def __init__(self, *, pretty: bool = False) -> None:
        self.pretty = pretty

    async def write(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            print(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    indent=2 if self.pretty else None,
                    separators=None if self.pretty else (",", ":"),
                )
            )

