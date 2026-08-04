from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from reverse_collector.errors import PluginError
from reverse_collector.models import RequestSpec, ResponseData, TaskConfig

if TYPE_CHECKING:
    from reverse_collector.context import RunContext


Record = dict[str, Any]
RecordBatch = list[Record]


@dataclass(slots=True)
class PageResult:
    records: RecordBatch = field(default_factory=list)
    next_request: RequestSpec | None = None
    checkpoint: dict[str, Any] | None = None
    done: bool = False


class CollectorPlugin(ABC):
    """Smallest extension point for a platform-specific collector."""

    name = "unnamed"
    description = ""

    def validate_task(self, task: TaskConfig) -> None:
        if not task.dataset:
            raise PluginError("dataset is required")

    async def setup(self, context: RunContext, task: TaskConfig) -> None:
        """Prepare login state or platform-specific resources."""

    async def refresh_auth(self, context: RunContext, task: TaskConfig) -> bool:
        """Refresh authentication and return whether the request should be retried."""
        return False

    @abstractmethod
    async def collect(
        self, context: RunContext, task: TaskConfig
    ) -> AsyncIterator[RecordBatch]:
        """Yield normalized or raw record batches."""
        if False:  # pragma: no cover - makes this an async generator for type checkers
            yield []

    async def teardown(self, context: RunContext, task: TaskConfig) -> None:
        """Release plugin-owned resources."""


class ApiCollectorPlugin(CollectorPlugin, ABC):
    """Convenience plugin for request/parse/next-request pagination."""

    @abstractmethod
    async def first_request(
        self,
        context: RunContext,
        task: TaskConfig,
        checkpoint: dict[str, Any] | None,
    ) -> RequestSpec | None:
        raise NotImplementedError

    @abstractmethod
    async def parse_page(
        self,
        context: RunContext,
        task: TaskConfig,
        request: RequestSpec,
        response: ResponseData,
    ) -> PageResult:
        raise NotImplementedError

    async def collect(
        self, context: RunContext, task: TaskConfig
    ) -> AsyncIterator[RecordBatch]:
        request = await self.first_request(context, task, context.checkpoint)
        max_pages = int(task.parameters.get("max_pages", 10_000))
        page_number = 0
        fingerprints: set[tuple[str, ...]] = set()

        while request is not None:
            page_number += 1
            if page_number > max_pages:
                raise PluginError(f"pagination exceeded max_pages={max_pages}")
            fingerprint = (
                request.method,
                request.url,
                _stable(request.params),
                _stable(request.json_body),
                _stable(request.form_body),
                _stable(request.content),
            )
            if fingerprint in fingerprints:
                raise PluginError(
                    "pagination generated the same request twice; refusing an infinite loop"
                )
            fingerprints.add(fingerprint)

            response = await context.request(request)
            result = await self.parse_page(context, task, request, response)
            if not isinstance(result, PageResult):
                raise PluginError(f"parse_page must return PageResult, got {type(result).__name__}")
            if result.checkpoint is not None:
                await context.save_checkpoint(result.checkpoint)
            if result.records or result.checkpoint is not None:
                yield result.records
            if result.done:
                break
            request = result.next_request


def _stable(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)
