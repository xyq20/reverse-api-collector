from __future__ import annotations

from collections import deque
from typing import Any

from reverse_collector.models import RequestSpec, ResponseData, RunSummary, TaskConfig
from reverse_collector.sinks.base import Sink
from reverse_collector.transports.base import Transport


def response(
    payload: bytes = b"{}",
    *,
    status: int = 200,
    transport: str = "fake",
    headers: dict[str, str] | None = None,
) -> ResponseData:
    return ResponseData(
        status_code=status,
        url="https://example.test/api",
        headers=headers or {"content-type": "application/json"},
        body=payload,
        transport=transport,
    )


class ScriptedTransport(Transport):
    def __init__(self, name: str, *events: Any) -> None:
        self.name = name
        self.events = deque(events)
        self.requests: list[RequestSpec] = []

    async def send(self, request: RequestSpec) -> ResponseData:
        self.requests.append(request)
        if not self.events:
            raise AssertionError(f"no scripted event left for {self.name}")
        event = self.events.popleft()
        if isinstance(event, BaseException):
            raise event
        if callable(event):
            event = event(request)
        event.transport = self.name
        return event


class CollectingSink(Sink):
    name = "collecting"

    def __init__(
        self,
        *,
        durable_per_batch: bool = True,
        fail_on_write: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.durable_per_batch = durable_per_batch
        self.fail_on_write = fail_on_write
        self.fail_on_commit = fail_on_commit
        self.records: list[dict[str, Any]] = []
        self.started = False
        self.finished = False
        self.aborted = False

    async def start(self, task: TaskConfig, summary: RunSummary) -> None:
        self.started = True

    async def write(self, records: list[dict[str, Any]]) -> None:
        if self.fail_on_write:
            raise RuntimeError("injected sink write failure")
        self.records.extend(records)

    async def commit_batch(self) -> None:
        if self.fail_on_commit:
            raise RuntimeError("injected sink commit failure")

    async def finish(self) -> None:
        self.finished = True

    async def abort(self) -> None:
        self.aborted = True


class DummyBrowser:
    started = False

    async def close(self) -> None:
        return None


class DummyRouter:
    def __init__(self) -> None:
        self.browser = DummyBrowser()
        self.closed = False

    async def close(self) -> None:
        self.closed = True

