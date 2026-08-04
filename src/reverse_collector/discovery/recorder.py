from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from reverse_collector.browser import BrowserManager
from reverse_collector.models import BrowserConfig
from reverse_collector.redaction import Redactor


@dataclass(slots=True)
class DiscoveryConfig:
    url: str
    output: str = "captures/discovery.jsonl"
    profile: str = "profiles/discovery"
    engine: str = "playwright"
    domains: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ("xhr", "fetch")
    include_response_bodies: bool = True
    max_body_bytes: int = 256 * 1024
    extra_secret_keys: list[str] = field(default_factory=list)


class DiscoveryRecorder:
    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config
        self.redactor = Redactor(config.extra_secret_keys)
        self.output = Path(config.output).expanduser().resolve()
        self.handle: Any = None
        self.pending: set[asyncio.Task[Any]] = set()
        self.request_ids: dict[int, str] = {}
        self._counter = 0
        self._write_lock = asyncio.Lock()

    def accepts(self, url: str, resource_type: str) -> bool:
        if self.config.resource_types and resource_type not in self.config.resource_types:
            return False
        if not self.config.domains:
            return True
        host = (urlsplit(url).hostname or "").lower()
        return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in self.config.domains)

    async def start(self, context: Any) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.output.open("w", encoding="utf-8", newline="\n")
        context.on("request", self._schedule_request)
        context.on("response", self._schedule_response)

    async def stop(self, context: Any) -> None:
        context.remove_listener("request", self._schedule_request)
        context.remove_listener("response", self._schedule_response)
        if self.pending:
            await asyncio.gather(*tuple(self.pending), return_exceptions=True)
        if self.handle is not None:
            self.handle.flush()
            self.handle.close()
            self.handle = None

    def _schedule_request(self, request: Any) -> None:
        if not self.accepts(request.url, request.resource_type):
            return
        self._track(asyncio.create_task(self._record_request(request)))

    def _schedule_response(self, response: Any) -> None:
        request = response.request
        if not self.accepts(request.url, request.resource_type):
            return
        self._track(asyncio.create_task(self._record_response(response)))

    def _track(self, task: asyncio.Task[Any]) -> None:
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    def _request_id(self, request: Any) -> str:
        key = id(request)
        current = self.request_ids.get(key)
        if current is None:
            self._counter += 1
            current = f"req-{self._counter:06d}"
            self.request_ids[key] = current
        return current

    async def _record_request(self, request: Any) -> None:
        headers = await request.all_headers()
        content_type = next(
            (value for key, value in headers.items() if key.lower() == "content-type"), ""
        )
        record = {
            "event": "request",
            "request_id": self._request_id(request),
            "captured_at": _now(),
            "page_url": self.redactor.redact_url(request.frame.url) if request.frame else None,
            "resource_type": request.resource_type,
            "method": request.method,
            "url": self.redactor.redact_url(request.url),
            "headers": self.redactor.redact_headers(headers),
            "body": self.redactor.redact_body(request.post_data, content_type),
        }
        await self._write(record)

    async def _record_response(self, response: Any) -> None:
        headers = await response.all_headers()
        content_type = next(
            (value for key, value in headers.items() if key.lower() == "content-type"), ""
        )
        record: dict[str, Any] = {
            "event": "response",
            "request_id": self._request_id(response.request),
            "captured_at": _now(),
            "status": response.status,
            "url": self.redactor.redact_url(response.url),
            "headers": self.redactor.redact_headers(headers),
        }
        if self.config.include_response_bodies:
            try:
                body = await response.body()
                if len(body) <= self.config.max_body_bytes and _is_text(content_type):
                    record["body"] = self.redactor.redact_body(
                        body.decode("utf-8", errors="replace"), content_type
                    )
                else:
                    record["body_meta"] = {
                        "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "omitted": True,
                    }
            except Exception as exc:  # noqa: BLE001 - browser body access has backend-specific errors
                record["body_error"] = type(exc).__name__
        await self._write(record)

    async def _write(self, record: dict[str, Any]) -> None:
        async with self._write_lock:
            if self.handle is not None:
                self.handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                self.handle.write("\n")
                self.handle.flush()


async def run_discovery(config: DiscoveryConfig) -> Path:
    browser = BrowserManager(
        BrowserConfig(
            engine=config.engine,
            user_data_dir=config.profile,
            headless=False,
            start_url=None,
        ),
        interactive=True,
    )
    recorder = DiscoveryRecorder(config)
    try:
        await browser.start()
        await recorder.start(browser.context)
        await browser.page.goto(config.url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.to_thread(
            input,
            "发现模式已启动。请在浏览器中操作目标页面，完成后回到这里按 Enter 停止采集...",
        )
        await recorder.stop(browser.context)
        return recorder.output
    finally:
        if browser.context is not None and recorder.handle is not None:
            await recorder.stop(browser.context)
        await browser.close()


def summarize_capture(path: str | Path) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("event") != "request":
                continue
            split = urlsplit(record["url"])
            key = (record.get("method", "GET"), split.scheme + "://" + split.netloc + split.path)
            group = groups.setdefault(
                key,
                {"method": key[0], "url": key[1], "count": 0, "resource_type": record.get("resource_type")},
            )
            group["count"] += 1
    return sorted(groups.values(), key=lambda item: (-item["count"], item["url"]))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _is_text(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(marker in lowered for marker in ("json", "text", "javascript", "xml", "form"))
