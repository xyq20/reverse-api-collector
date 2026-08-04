from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

TransportName = Literal["auto", "http", "browser_fetch"]


@dataclass(slots=True)
class RequestSpec:
    method: str
    url: str
    endpoint_id: str = ""
    params: dict[str, Any] | list[tuple[str, Any]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any = None
    form_body: dict[str, Any] | list[tuple[str, Any]] | None = None
    content: str | bytes | None = None
    timeout: float | None = None
    transport: TransportName = "auto"
    retryable: bool | None = None
    fallback_on_auth: bool = False
    fallback_on_network: bool = False
    expected_statuses: tuple[int, ...] = tuple(range(200, 300))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.method = self.method.upper()
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"request URL must be absolute: {self.url!r}")
        bodies = sum(
            value is not None for value in (self.json_body, self.form_body, self.content)
        )
        if bodies > 1:
            raise ValueError("json_body, form_body and content are mutually exclusive")

    @property
    def may_retry(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return self.method in {"GET", "HEAD", "OPTIONS"}


@dataclass(slots=True)
class ResponseData:
    status_code: int
    url: str
    headers: dict[str, str]
    body: bytes
    transport: str
    elapsed_seconds: float = 0.0

    @property
    def text(self) -> str:
        encoding = "utf-8"
        content_type = next(
            (value for key, value in self.headers.items() if key.lower() == "content-type"),
            "",
        )
        marker = "charset="
        if marker in content_type.lower():
            encoding = (
                content_type.lower().split(marker, 1)[1].split(";", 1)[0].strip().strip('"\'')
            )
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


@dataclass(slots=True)
class RetryConfig:
    attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.2
    retry_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)


@dataclass(slots=True)
class TransportConfig:
    mode: TransportName = "auto"
    order: tuple[str, ...] = ("http", "browser_fetch")
    timeout: float = 30.0
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    verify_tls: bool = True
    follow_redirects: bool = True
    remember_successful_transport: bool = True
    max_response_bytes: int = 20 * 1024 * 1024


@dataclass(slots=True)
class BrowserConfig:
    engine: str = "playwright"
    user_data_dir: str = "profiles/default"
    start_url: str | None = None
    login_url: str | None = None
    headless: bool = False
    timeout_ms: int = 30_000
    locale: str = "zh-CN"
    timezone_id: str = "Asia/Shanghai"
    pause_for_login: bool = False
    humanize: bool = True


@dataclass(slots=True)
class PipelineConfig:
    rename: dict[str, str] = field(default_factory=dict)
    include_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    dedupe_keys: tuple[str, ...] = ()
    on_missing: str = "error"


@dataclass(slots=True)
class CheckpointConfig:
    enabled: bool = True
    directory: str = "checkpoints"
    resume: bool = True
    clear_on_success: bool = False


@dataclass(slots=True)
class SinkConfig:
    type: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskConfig:
    name: str
    plugin: str
    dataset: str
    parameters: dict[str, Any] = field(default_factory=dict)
    transport: TransportConfig = field(default_factory=TransportConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    checkpoint: CheckpointConfig = field(default_factory=CheckpointConfig)
    outputs: list[SinkConfig] = field(default_factory=list)
    config_path: str | None = None


@dataclass(slots=True)
class RunSummary:
    task: str
    plugin: str
    dataset: str
    records_seen: int = 0
    records_written: int = 0
    records_skipped: int = 0
    batches: int = 0
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    finished_at: str | None = None
    transports_used: dict[str, int] = field(default_factory=dict)

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
