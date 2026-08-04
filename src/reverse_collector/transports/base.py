from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC
from email.utils import parsedate_to_datetime

from reverse_collector.errors import (
    AuthenticationError,
    HttpIncompatibleError,
    HttpStatusError,
    RateLimitError,
)
from reverse_collector.models import RequestSpec, ResponseData


class Transport(ABC):
    name = "unknown"

    @abstractmethod
    async def send(self, request: RequestSpec) -> ResponseData:
        raise NotImplementedError

    async def close(self) -> None:
        return None


def validate_response(request: RequestSpec, response: ResponseData) -> ResponseData:
    status = response.status_code
    incompatible = set(request.metadata.get("incompatible_statuses", ()))
    auth_statuses = set(request.metadata.get("auth_statuses", (401,)))
    if status in incompatible:
        raise HttpIncompatibleError(
            f"{response.transport} is incompatible with endpoint {request.endpoint_id or request.url} "
            f"(HTTP {status})"
        )
    if status in auth_statuses:
        raise AuthenticationError(f"authentication rejected with HTTP {status}")
    if status == 429:
        raise RateLimitError(
            f"rate limited by {request.url}",
            retry_after=_retry_after(response.headers),
        )
    if status not in request.expected_statuses:
        raise HttpStatusError(status, response.url, response.text[:300])

    if request.metadata.get("expect_json"):
        content_type = _header(response.headers, "content-type").lower()
        preview = response.body.lstrip()[:100].lower()
        if "json" not in content_type and preview.startswith((b"<!doctype html", b"<html")):
            raise AuthenticationError("API returned an HTML page instead of JSON")
    markers = request.metadata.get("login_html_markers", ())
    if markers:
        text = response.text[:20_000]
        if any(str(marker) in text for marker in markers):
            raise AuthenticationError("API response contains a configured login marker")
    return response


def _header(headers: dict[str, str], name: str) -> str:
    lowered = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered), "")


def _retry_after(headers: dict[str, str]) -> float | None:
    raw = _header(headers, "retry-after").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            from datetime import datetime

            when = parsedate_to_datetime(raw)
            return max(0.0, (when - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

