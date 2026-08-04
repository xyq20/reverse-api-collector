from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

from reverse_collector.errors import ConfigurationError
from reverse_collector.models import (
    BrowserConfig,
    CheckpointConfig,
    PipelineConfig,
    RetryConfig,
    SinkConfig,
    TaskConfig,
    TransportConfig,
)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if name in os.environ:
                return os.environ[name]
            if default is not None:
                return default
            raise ConfigurationError(f"environment variable {name!r} is required")

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _only(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigurationError(f"unknown keys in [{section}]: {names}")


def load_task_config(path: str | Path) -> TaskConfig:
    source = Path(path)
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"config file not found: {source}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid TOML in {source}: {exc}") from exc

    raw = _expand_env(raw)
    _only(
        raw,
        {"task", "transport", "retry", "browser", "pipeline", "checkpoint", "outputs"},
        "root",
    )
    task_data = raw.get("task") or {}
    if not isinstance(task_data, dict):
        raise ConfigurationError("[task] must be a table")
    _only(task_data, {"name", "plugin", "dataset", "parameters"}, "task")
    missing = [key for key in ("name", "plugin", "dataset") if not task_data.get(key)]
    if missing:
        raise ConfigurationError(f"missing required [task] values: {', '.join(missing)}")

    transport_data = raw.get("transport") or {}
    if not isinstance(transport_data, dict):
        raise ConfigurationError("[transport] must be a table")
    _only(
        transport_data,
        {
            "mode", "order", "timeout", "headers", "cookies", "verify_tls",
            "follow_redirects", "remember_successful_transport", "max_response_bytes",
        },
        "transport",
    )
    retry_data = raw.get("retry") or {}
    if not isinstance(retry_data, dict):
        raise ConfigurationError("[retry] must be a table")
    _only(
        retry_data,
        {"attempts", "base_delay", "max_delay", "jitter", "retry_statuses"},
        "retry",
    )
    browser_data = raw.get("browser") or {}
    if not isinstance(browser_data, dict):
        raise ConfigurationError("[browser] must be a table")
    _only(
        browser_data,
        {
            "engine", "user_data_dir", "start_url", "login_url", "headless",
            "timeout_ms", "locale", "timezone_id", "pause_for_login", "humanize",
        },
        "browser",
    )
    pipeline_data = raw.get("pipeline") or {}
    if not isinstance(pipeline_data, dict):
        raise ConfigurationError("[pipeline] must be a table")
    _only(
        pipeline_data,
        {"rename", "include_fields", "required_fields", "dedupe_keys", "on_missing"},
        "pipeline",
    )
    checkpoint_data = raw.get("checkpoint") or {}
    if not isinstance(checkpoint_data, dict):
        raise ConfigurationError("[checkpoint] must be a table")
    _only(
        checkpoint_data,
        {"enabled", "directory", "resume", "clear_on_success"},
        "checkpoint",
    )

    outputs_raw = raw.get("outputs") or []
    if not isinstance(outputs_raw, list):
        raise ConfigurationError("[[outputs]] must be an array of tables")
    outputs: list[SinkConfig] = []
    for index, output in enumerate(outputs_raw):
        if not isinstance(output, dict) or not output.get("type"):
            raise ConfigurationError(f"outputs[{index}] requires a type")
        options = {key: value for key, value in output.items() if key != "type"}
        outputs.append(
            SinkConfig(
                type=str(output["type"]),
                options=options,
            )
        )
    if not outputs:
        raise ConfigurationError("at least one [[outputs]] destination is required")

    transport = TransportConfig(**transport_data)
    transport.order = tuple(transport.order)
    retry = RetryConfig(**retry_data)
    retry.retry_statuses = tuple(retry.retry_statuses)
    pipeline = PipelineConfig(**pipeline_data)
    pipeline.include_fields = tuple(pipeline.include_fields)
    pipeline.required_fields = tuple(pipeline.required_fields)
    pipeline.dedupe_keys = tuple(pipeline.dedupe_keys)

    if transport.mode not in {"auto", "http", "browser_fetch"}:
        raise ConfigurationError(f"unsupported transport mode: {transport.mode}")
    if not transport.order or any(name not in {"http", "browser_fetch"} for name in transport.order):
        raise ConfigurationError("transport.order may only contain http and browser_fetch")
    if retry.attempts < 1:
        raise ConfigurationError("retry.attempts must be at least 1")
    if transport.timeout <= 0:
        raise ConfigurationError("transport.timeout must be greater than 0")
    if transport.max_response_bytes <= 0:
        raise ConfigurationError("transport.max_response_bytes must be greater than 0")
    if not isinstance(transport.headers, dict) or not isinstance(transport.cookies, dict):
        raise ConfigurationError("transport.headers and transport.cookies must be tables")
    if any(value < 0 for value in (retry.base_delay, retry.max_delay, retry.jitter)):
        raise ConfigurationError("retry delays and jitter cannot be negative")
    if not isinstance(task_data.get("parameters", {}), dict):
        raise ConfigurationError("task.parameters must be an inline table or table")
    if pipeline.on_missing not in {"error", "skip"}:
        raise ConfigurationError("pipeline.on_missing must be 'error' or 'skip'")

    return TaskConfig(
        name=str(task_data["name"]),
        plugin=str(task_data["plugin"]),
        dataset=str(task_data["dataset"]),
        parameters=dict(task_data.get("parameters") or {}),
        transport=transport,
        retry=retry,
        browser=BrowserConfig(**browser_data),
        pipeline=pipeline,
        checkpoint=CheckpointConfig(**checkpoint_data),
        outputs=outputs,
        config_path=str(source.resolve()),
    )
