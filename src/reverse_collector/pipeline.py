from __future__ import annotations

import json
from typing import Any

from reverse_collector.errors import DataValidationError
from reverse_collector.models import PipelineConfig


class RecordPipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._seen: set[tuple[str, ...]] = set()

    def process(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        output: list[dict[str, Any]] = []
        skipped = 0
        for original in records:
            if not isinstance(original, dict):
                raise DataValidationError(
                    f"plugin yielded {type(original).__name__}; records must be dictionaries"
                )
            record: dict[str, Any] = {}
            for key, value in original.items():
                target = self.config.rename.get(key, key)
                if target in record and target != key:
                    raise DataValidationError(
                        f"field rename collision: more than one source maps to {target!r}"
                    )
                record[target] = value
            missing = [
                field
                for field in self.config.required_fields
                if field not in record or record[field] in (None, "")
            ]
            if missing:
                if self.config.on_missing == "skip":
                    skipped += 1
                    continue
                raise DataValidationError(
                    f"record is missing required fields: {', '.join(missing)}"
                )
            if self.config.include_fields:
                record = {
                    field: record.get(field) for field in self.config.include_fields
                }
            if self.config.dedupe_keys:
                absent_keys = [field for field in self.config.dedupe_keys if field not in record]
                if absent_keys:
                    if self.config.on_missing == "skip":
                        skipped += 1
                        continue
                    raise DataValidationError(
                        f"record is missing dedupe fields: {', '.join(absent_keys)}"
                    )
                key = tuple(
                    _stable_value(record.get(field)) for field in self.config.dedupe_keys
                )
                if key in self._seen:
                    skipped += 1
                    continue
                self._seen.add(key)
            output.append(record)
        return output, skipped


def _stable_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "" if value is None else str(value)
