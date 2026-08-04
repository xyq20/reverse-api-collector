from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from reverse_collector.checkpoints import CheckpointStore
from reverse_collector.errors import AuthenticationError, CheckpointError
from reverse_collector.models import RequestSpec, ResponseData, TaskConfig
from reverse_collector.transports.router import TransportRouter

AuthRefresher = Callable[["RunContext", TaskConfig], Awaitable[bool]]


class RunContext:
    def __init__(
        self,
        task: TaskConfig,
        router: TransportRouter,
        checkpoint_store: CheckpointStore,
        *,
        interactive: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.task = task
        self.router = router
        self.checkpoint_store = checkpoint_store
        self.interactive = interactive
        self.logger = logger or logging.getLogger("reverse_collector")
        self.checkpoint: dict[str, Any] | None = None
        self._pending_checkpoint: dict[str, Any] | None = None
        self._auth_refresher: AuthRefresher | None = None
        self._auth_lock = asyncio.Lock()
        self._auth_generation = 0
        self.transport_counts: dict[str, int] = {}
        self.identity = _task_identity(task)

    async def load_checkpoint(self) -> None:
        envelope = await self.checkpoint_store.load()
        if envelope is None:
            self.checkpoint = None
            return
        meta = envelope.get("meta")
        state = envelope.get("state")
        if not isinstance(meta, dict) or not isinstance(state, dict):
            raise CheckpointError("checkpoint requires object fields 'meta' and 'state'")
        if meta.get("identity") != self.identity["identity"]:
            raise CheckpointError(
                "checkpoint belongs to a different task configuration; move or clear it explicitly"
            )
        self.checkpoint = state

    def set_auth_refresher(self, refresher: AuthRefresher) -> None:
        self._auth_refresher = refresher

    async def request(self, request: RequestSpec) -> ResponseData:
        generation = self._auth_generation
        try:
            response = await self.router.send(request, allow_auth_fallback=False)
        except AuthenticationError:
            async with self._auth_lock:
                if generation == self._auth_generation:
                    if self._auth_refresher is None:
                        raise
                    refreshed = await self._auth_refresher(self, self.task)
                    if not refreshed:
                        raise
                    self._auth_generation += 1
                    self.router.clear_affinity(request)
                    await self.router.sync_browser_cookies_to_http()
            response = await self.router.send(request, allow_auth_fallback=True)
        self.transport_counts[response.transport] = self.transport_counts.get(response.transport, 0) + 1
        return response

    async def browser_page(self, url: str | None = None) -> Any:
        return await self.router.browser.ensure_page(url)

    async def save_checkpoint(self, state: dict[str, Any]) -> None:
        """Stage a cursor; the runner persists it only after sinks commit the batch."""
        self._pending_checkpoint = {
            "meta": dict(self.identity),
            "state": state,
        }

    async def commit_checkpoint(self) -> None:
        if self._pending_checkpoint is None:
            return
        await self.checkpoint_store.save(self._pending_checkpoint)
        self.checkpoint = dict(self._pending_checkpoint["state"])
        self._pending_checkpoint = None

    async def clear_checkpoint(self) -> None:
        self._pending_checkpoint = None
        self.checkpoint = None
        await self.checkpoint_store.clear()


def _task_identity(task: TaskConfig) -> dict[str, str]:
    schema_version = str(task.parameters.get("schema_version", "1"))
    account = str(task.parameters.get("account", ""))
    window = task.parameters.get("date") or {
        "start": task.parameters.get("start_date"),
        "end": task.parameters.get("end_date"),
    }
    parameter_hash = hashlib.sha256(
        json.dumps(
            task.parameters,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    canonical = {
        "task": task.name,
        "plugin": task.plugin,
        "dataset": task.dataset,
        "account_hash": hashlib.sha256(account.encode("utf-8")).hexdigest()[:16],
        "window": window,
        "schema_version": schema_version,
        "parameters_hash": parameter_hash,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "identity": digest,
        "task": task.name,
        "plugin": task.plugin,
        "dataset": task.dataset,
        "schema_version": schema_version,
        "parameters_hash": parameter_hash,
    }
