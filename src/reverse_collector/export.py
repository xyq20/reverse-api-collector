"""Reusable polling primitive for platform export APIs.

Plugins own the endpoint details. This module provides the safe state machine used
by APIs that create an export task, report progress, then expose a signed download
URL. It deliberately does not retry task creation: a timed-out create call has an
unknown outcome and blindly replaying it may create duplicate exports.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from reverse_collector.errors import PluginError


@dataclass(frozen=True, slots=True)
class ExportTicket:
    id: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExportStatus:
    state: Literal["pending", "ready", "failed", "expired"]
    download_url: str | None = None
    filename: str | None = None
    retry_after: float | None = None
    message: str | None = None


class ExportAdapter(Protocol):
    async def create(self) -> ExportTicket:
        """Create the job once. Persist its ID before entering the poll loop."""

    async def get_status(self, ticket: ExportTicket) -> ExportStatus:
        """Return a normalized platform status."""


async def wait_for_export(
    adapter: ExportAdapter,
    *,
    ticket: ExportTicket | None = None,
    timeout_seconds: float = 300,
    initial_delay: float = 1,
    max_delay: float = 15,
    jitter: float = 0.15,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] | None = None,
    on_ticket: Callable[[ExportTicket], Awaitable[None]] | None = None,
) -> tuple[ExportTicket, ExportStatus]:
    """Wait until an export is ready, preserving an existing ticket on resume."""
    if timeout_seconds <= 0 or initial_delay < 0 or max_delay <= 0 or jitter < 0:
        raise ValueError("invalid export polling timing configuration")
    if monotonic is None:
        from time import monotonic as default_monotonic

        monotonic = default_monotonic
    if ticket is None:
        ticket = await adapter.create()
        if not ticket.id:
            raise PluginError("export adapter returned a ticket without an ID")
        if on_ticket is not None:
            await on_ticket(ticket)

    deadline = monotonic() + timeout_seconds
    delay = initial_delay
    while True:
        status = await adapter.get_status(ticket)
        if status.state == "ready":
            if not status.download_url:
                raise PluginError("export was marked ready without a download URL")
            return ticket, status
        if status.state == "failed":
            raise PluginError(status.message or f"export {ticket.id} failed")
        if status.state == "expired":
            raise PluginError(
                status.message or f"export {ticket.id} expired; create a new task explicitly"
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError(f"export {ticket.id} was not ready after {timeout_seconds:g}s")
        next_delay = status.retry_after if status.retry_after is not None else delay
        next_delay = min(remaining, max(0.0, next_delay))
        if jitter and next_delay:
            next_delay = min(remaining, next_delay * (1 + random.random() * jitter))
        await sleep(next_delay)
        delay = min(max_delay, max(initial_delay, delay * 2))
