from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from reverse_collector.models import RunSummary, TaskConfig


class Sink(ABC):
    """Output contract. Required sinks are committed before a checkpoint advances."""

    name = "unknown"
    durable_per_batch = False

    async def start(self, task: TaskConfig, summary: RunSummary) -> None:
        return None

    @abstractmethod
    async def write(self, records: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    async def commit_batch(self) -> None:
        return None

    async def finish(self) -> None:
        return None

    async def abort(self) -> None:
        return None

