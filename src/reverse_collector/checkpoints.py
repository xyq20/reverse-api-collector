from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from reverse_collector.errors import CheckpointError
from reverse_collector.models import CheckpointConfig


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value).strip(" .")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if not cleaned or cleaned.upper() in reserved:
        cleaned = "task"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:80]}-{digest}"


class CheckpointStore:
    def __init__(self, task_name: str, config: CheckpointConfig) -> None:
        self.enabled = config.enabled
        self.resume = config.resume
        self.clear_on_success = config.clear_on_success
        self.path = Path(config.directory) / f"{_safe_name(task_name)}.json"

    async def load(self) -> dict[str, Any] | None:
        if not self.enabled or not self.resume or not self.path.exists():
            return None
        return await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"cannot read checkpoint {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise CheckpointError(f"checkpoint {self.path} must contain a JSON object")
        return data

    async def save(self, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        # The payload is deliberately small. A synchronous atomic replace avoids a
        # cancelled to_thread call completing after the task has reported failure.
        self._save_sync(value)

    def _save_sync(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    async def clear(self) -> None:
        if self.enabled:
            self.path.unlink(missing_ok=True)
