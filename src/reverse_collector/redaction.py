from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

_SENSITIVE_KEY = re.compile(
    r"(^|[-_])(authorization|cookie|set-cookie|password|passwd|secret|"
    r"access[-_]?token|refresh[-_]?token|token|csrf|xsrf|api[-_]?key|session|signature|sign)([-_]|$)",
    re.IGNORECASE,
)


class Redactor:
    """Structure-preserving redaction shared by discovery, logs, and samples."""

    def __init__(self, extra_keys: list[str] | None = None) -> None:
        self.extra_keys = {key.lower() for key in (extra_keys or [])}
        self._known_secrets: set[str] = set()

    def is_sensitive(self, key: str) -> bool:
        return key.lower() in self.extra_keys or bool(_SENSITIVE_KEY.search(key))

    def redact_headers(self, headers: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._placeholder(key, value) if self.is_sensitive(key) else self.redact(value)
            for key, value in headers.items()
        }

    def redact_url(self, url: str) -> str:
        parts = urlsplit(url)
        query: list[tuple[str, str]] = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if self.is_sensitive(key):
                query.append((key, self._placeholder(key, value)))
            else:
                query.append((key, self.redact_text(value)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def redact(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and self.is_sensitive(key):
            return self._placeholder(key, value)
        if isinstance(value, dict):
            return {str(k): self.redact(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def redact_body(self, body: str | None, content_type: str = "") -> Any:
        if body is None:
            return None
        stripped = body.strip()
        if "json" in content_type.lower() or stripped.startswith(("{", "[")):
            try:
                return self.redact(json.loads(body))
            except json.JSONDecodeError:
                pass
        if "x-www-form-urlencoded" in content_type.lower():
            return [
                [key, self.redact(value, key=key)]
                for key, value in parse_qsl(body, keep_blank_values=True)
            ]
        return self.redact_text(body)

    def redact_text(self, text: str) -> str:
        result = text
        for secret in sorted(self._known_secrets, key=len, reverse=True):
            if not secret:
                continue
            result = result.replace(secret, "${REDACTED}")
            result = result.replace(quote(secret, safe=""), "${REDACTED}")
        return result

    def _placeholder(self, key: str, value: Any) -> str:
        if isinstance(value, str) and len(value) >= 4:
            self._known_secrets.add(value)
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper()
        return "${" + (normalized or "SECRET") + "}"
