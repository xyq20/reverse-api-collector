from __future__ import annotations

import unittest

from reverse_collector.errors import (
    AuthenticationError,
    HttpStatusError,
    NetworkError,
    TransportUnavailable,
)
from reverse_collector.models import RequestSpec, RetryConfig, TransportConfig
from reverse_collector.transports.retry import send_with_retry
from reverse_collector.transports.router import TransportRouter
from tests.fakes import DummyBrowser, ScriptedTransport, response


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_and_total_attempt_count(self) -> None:
        transport = ScriptedTransport(
            "http",
            NetworkError("one"),
            NetworkError("two"),
            response(),
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        result = await send_with_retry(
            transport,
            RequestSpec("GET", "https://example.test"),
            RetryConfig(attempts=3, base_delay=1, max_delay=10, jitter=0),
            sleep=fake_sleep,
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(sleeps, [1, 2])

    async def test_non_idempotent_post_is_not_retried(self) -> None:
        transport = ScriptedTransport("http", NetworkError("unknown outcome"), response())
        with self.assertRaises(NetworkError):
            await send_with_retry(
                transport,
                RequestSpec("POST", "https://example.test/export"),
                RetryConfig(attempts=3),
            )
        self.assertEqual(len(transport.requests), 1)


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_transport_falls_back_and_becomes_sticky(self) -> None:
        primary = ScriptedTransport("http", TransportUnavailable("missing"))
        browser = ScriptedTransport("browser_fetch", response(), response())
        router = TransportRouter(
            TransportConfig(mode="auto", order=("http", "browser_fetch")),
            RetryConfig(attempts=1),
            DummyBrowser(),
            transports={"http": primary, "browser_fetch": browser},
        )
        request = RequestSpec("GET", "https://example.test/api", endpoint_id="rows")
        first = await router.send(request)
        second = await router.send(request)
        self.assertEqual(first.transport, "browser_fetch")
        self.assertEqual(second.transport, "browser_fetch")
        self.assertEqual(len(primary.requests), 1)
        self.assertEqual(len(browser.requests), 2)

    async def test_business_error_and_auth_do_not_blindly_fallback(self) -> None:
        for error in (HttpStatusError(400, "https://example.test"), AuthenticationError("login")):
            primary = ScriptedTransport("http", error)
            browser = ScriptedTransport("browser_fetch", response())
            router = TransportRouter(
                TransportConfig(mode="auto", order=("http", "browser_fetch")),
                RetryConfig(attempts=1),
                DummyBrowser(),
                transports={"http": primary, "browser_fetch": browser},
            )
            with self.assertRaises(type(error)):
                await router.send(RequestSpec("GET", "https://example.test/api"))
            self.assertEqual(len(browser.requests), 0)


if __name__ == "__main__":
    unittest.main()

