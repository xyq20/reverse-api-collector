from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from reverse_collector.browser import BrowserManager
from reverse_collector.errors import (
    AuthenticationError,
    HttpIncompatibleError,
    NetworkError,
    TransportError,
    TransportUnavailable,
)
from reverse_collector.models import RequestSpec, ResponseData, RetryConfig, TransportConfig
from reverse_collector.transports.base import Transport
from reverse_collector.transports.browser_fetch import BrowserFetchTransport
from reverse_collector.transports.http import HttpTransport
from reverse_collector.transports.retry import send_with_retry


class TransportRouter:
    def __init__(
        self,
        config: TransportConfig,
        retry: RetryConfig,
        browser: BrowserManager,
        *,
        transports: dict[str, Transport] | None = None,
    ) -> None:
        self.config = config
        self.retry = retry
        self.browser = browser
        self._transports = transports or {
            "http": HttpTransport(config),
            "browser_fetch": BrowserFetchTransport(config, browser),
        }
        self._affinity: dict[str, str] = {}

    def _names(self, request: RequestSpec, *, allow_auth_fallback: bool) -> list[str]:
        mode = request.transport if request.transport != "auto" else self.config.mode
        if mode != "auto":
            return [mode]
        names = list(self.config.order)
        key = self._affinity_key(request)
        preferred = self._affinity.get(key)
        if preferred in names:
            names.remove(preferred)
            names.insert(0, preferred)
        return names

    async def send(
        self, request: RequestSpec, *, allow_auth_fallback: bool = False
    ) -> ResponseData:
        names = self._names(request, allow_auth_fallback=allow_auth_fallback)
        last_error: BaseException | None = None
        for index, name in enumerate(names):
            transport = self._transports.get(name)
            if transport is None:
                last_error = TransportUnavailable(f"transport is not configured: {name}")
            else:
                try:
                    response = await send_with_retry(transport, request, self.retry)
                    if self.config.remember_successful_transport and len(names) > 1:
                        self._affinity[self._affinity_key(request)] = name
                    return response
                except asyncio.CancelledError:
                    raise
                except AuthenticationError as exc:
                    last_error = exc
                    if not (allow_auth_fallback and request.fallback_on_auth):
                        raise
                except (TransportUnavailable, HttpIncompatibleError) as exc:
                    last_error = exc
                except NetworkError as exc:
                    last_error = exc
                    if not request.fallback_on_network:
                        raise
                except TransportError:
                    raise
            if index == len(names) - 1:
                break
        if last_error is None:
            raise TransportUnavailable("no transport candidates were configured")
        raise last_error

    def clear_affinity(self, request: RequestSpec | None = None) -> None:
        if request is None:
            self._affinity.clear()
        else:
            self._affinity.pop(self._affinity_key(request), None)

    async def sync_browser_cookies_to_http(self) -> None:
        http = self._transports.get("http")
        if self.browser.started and isinstance(http, HttpTransport):
            await http.update_cookies(await self.browser.cookies())

    def _affinity_key(self, request: RequestSpec) -> str:
        return str(
            request.metadata.get("affinity_key")
            or request.endpoint_id
            or urlsplit(request.url).netloc
        )

    async def close(self) -> None:
        errors: list[BaseException] = []
        for transport in self._transports.values():
            try:
                await transport.close()
            except Exception as exc:  # noqa: BLE001 - close every configured extension
                errors.append(exc)
        try:
            await self.browser.close()
        except Exception as exc:  # noqa: BLE001 - preserve earlier close failures
            errors.append(exc)
        if errors:
            raise errors[0]
