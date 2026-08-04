from __future__ import annotations

import json
import unittest
from typing import Any

from reverse_collector.errors import PluginError
from reverse_collector.models import RequestSpec, TaskConfig
from reverse_collector.plugin import ApiCollectorPlugin, PageResult
from tests.fakes import response


class FakeContext:
    def __init__(self) -> None:
        self.checkpoint = None
        self.requests: list[RequestSpec] = []
        self.staged: list[dict[str, Any]] = []

    async def request(self, request: RequestSpec):
        self.requests.append(request)
        return response(json.dumps({"offset": request.json_body["offset"]}).encode())

    async def save_checkpoint(self, state: dict[str, Any]) -> None:
        self.staged.append(state)


class BodyOffsetPlugin(ApiCollectorPlugin):
    async def first_request(self, context, task, checkpoint):
        return RequestSpec("POST", "https://example.test/api", json_body={"offset": 0}, retryable=True)

    async def parse_page(self, context, task, request, api_response):
        offset = api_response.json()["offset"]
        next_offset = offset + 10
        return PageResult(
            records=[{"offset": offset}],
            next_request=None if offset >= 20 else RequestSpec(
                "POST", "https://example.test/api", json_body={"offset": next_offset}, retryable=True
            ),
            checkpoint={"offset": next_offset},
            done=offset >= 20,
        )


class IdenticalBodyPlugin(BodyOffsetPlugin):
    async def parse_page(self, context, task, request, api_response):
        return PageResult(
            records=[{"offset": 0}],
            next_request=RequestSpec(
                "POST", "https://example.test/api", json_body={"offset": 0}, retryable=True
            ),
        )


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_body_offset_pages_are_not_cycle(self) -> None:
        context = FakeContext()
        task = TaskConfig("body-pages", "fake", "rows")
        batches = [batch async for batch in BodyOffsetPlugin().collect(context, task)]
        self.assertEqual([batch[0]["offset"] for batch in batches], [0, 10, 20])
        self.assertEqual(len(context.requests), 3)

    async def test_identical_post_body_is_cycle(self) -> None:
        context = FakeContext()
        task = TaskConfig("body-cycle", "fake", "rows")
        with self.assertRaises(PluginError):
            _ = [batch async for batch in IdenticalBodyPlugin().collect(context, task)]


if __name__ == "__main__":
    unittest.main()

