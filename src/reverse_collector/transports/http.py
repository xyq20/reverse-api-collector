from __future__ import annotations

import time
from typing import Any

from reverse_collector.errors import NetworkError, TransportUnavailable
from reverse_collector.models import RequestSpec, ResponseData, TransportConfig
from reverse_collector.transports.base import Transport, validate_response


class HttpTransport(Transport):
    name = "http"

    def __init__(self, config: TransportConfig) -> None:
        self.config = config
        self._client: Any = None

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import httpx
        except ImportError as exc:
            raise TransportUnavailable(
                "httpx is not installed; install with 'pip install -e .[http]'."
            ) from exc
        self._client = httpx.AsyncClient(
            headers=self.config.headers,
            cookies=self.config.cookies,
            verify=self.config.verify_tls,
            follow_redirects=self.config.follow_redirects,
            timeout=self.config.timeout,
        )
        return self._client

    async def update_cookies(self, cookies: list[dict[str, Any]]) -> None:
        client = await self._ensure_client()
        for cookie in cookies:
            client.cookies.set(
                cookie["name"],
                cookie.get("value", ""),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

    async def send(self, request: RequestSpec) -> ResponseData:
        client = await self._ensure_client()
        started = time.perf_counter()
        try:
            outgoing = client.build_request(
                request.method,
                request.url,
                params=request.params,
                headers=request.headers,
                json=request.json_body,
                data=request.form_body,
                content=request.content,
                timeout=request.timeout or self.config.timeout,
            )
            response = await client.send(outgoing, stream=True)
            chunks: list[bytes] = []
            size = 0
            try:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.config.max_response_bytes:
                        raise NetworkError(
                            f"response exceeds max_response_bytes={self.config.max_response_bytes}"
                        )
                    chunks.append(chunk)
            finally:
                await response.aclose()
        except NetworkError:
            raise
        except Exception as exc:
            module = type(exc).__module__
            if module.startswith("httpx") or isinstance(exc, OSError):
                raise NetworkError(f"{request.method} {request.url} failed: {exc}") from exc
            raise
        result = ResponseData(
            status_code=response.status_code,
            url=str(response.url),
            headers=dict(response.headers),
            body=b"".join(chunks),
            transport=self.name,
            elapsed_seconds=time.perf_counter() - started,
        )
        return validate_response(request, result)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

