from __future__ import annotations

import base64
import json
import time
from urllib.parse import urlencode

from reverse_collector.browser import BrowserManager
from reverse_collector.errors import NetworkError
from reverse_collector.models import RequestSpec, ResponseData, TransportConfig
from reverse_collector.transports.base import Transport, validate_response

_FETCH_SCRIPT = r"""async (args) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), args.timeoutMs);
    try {
        const response = await fetch(args.url, {
            method: args.method,
            credentials: "include",
            headers: args.headers,
            body: args.body,
            signal: controller.signal,
        });
        const bytes = new Uint8Array(await response.arrayBuffer());
        let binary = "";
        const chunkSize = 0x8000;
        for (let offset = 0; offset < bytes.length; offset += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
        }
        return {
            ok: true,
            status: response.status,
            url: response.url,
            headers: Object.fromEntries(response.headers.entries()),
            base64: btoa(binary),
            size: bytes.length,
        };
    } catch (error) {
        return {ok: false, error: error instanceof Error ? error.message : String(error)};
    } finally {
        clearTimeout(timer);
    }
}"""


class BrowserFetchTransport(Transport):
    name = "browser_fetch"

    def __init__(self, config: TransportConfig, browser: BrowserManager) -> None:
        self.config = config
        self.browser = browser

    async def send(self, request: RequestSpec) -> ResponseData:
        page = await self.browser.ensure_page(request.metadata.get("required_origin"))
        params = request.params
        query = urlencode(params, doseq=True)
        url = request.url + (("&" if "?" in request.url else "?") + query if query else "")
        headers = {**self.config.headers, **request.headers}
        forbidden = {"cookie", "host", "origin", "referer", "user-agent", "content-length"}
        headers = {key: value for key, value in headers.items() if key.lower() not in forbidden}
        body = None
        if request.json_body is not None:
            body = json.dumps(request.json_body, ensure_ascii=False, separators=(",", ":"))
            headers.setdefault("content-type", "application/json")
        elif request.form_body is not None:
            body = urlencode(request.form_body, doseq=True)
            headers.setdefault("content-type", "application/x-www-form-urlencoded")
        elif isinstance(request.content, bytes):
            body = request.content.decode("utf-8")
        else:
            body = request.content

        started = time.perf_counter()
        async with self.browser.request_lock:
            result = await page.evaluate(
                _FETCH_SCRIPT,
                {
                    "url": url,
                    "method": request.method,
                    "headers": headers,
                    "body": body,
                    "timeoutMs": int((request.timeout or self.config.timeout) * 1000),
                },
            )
        if not result.get("ok"):
            raise NetworkError(f"browser fetch {request.method} {url} failed: {result.get('error')}")
        if int(result.get("size", 0)) > self.config.max_response_bytes:
            raise NetworkError(
                f"response exceeds max_response_bytes={self.config.max_response_bytes}"
            )
        response = ResponseData(
            status_code=int(result["status"]),
            url=str(result.get("url") or url),
            headers={str(key): str(value) for key, value in result.get("headers", {}).items()},
            body=base64.b64decode(result.get("base64", "")),
            transport=self.name,
            elapsed_seconds=time.perf_counter() - started,
        )
        return validate_response(request, response)

