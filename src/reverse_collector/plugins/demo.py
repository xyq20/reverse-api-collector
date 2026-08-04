from __future__ import annotations

from typing import Any

from reverse_collector.context import RunContext
from reverse_collector.errors import PluginError
from reverse_collector.models import RequestSpec, ResponseData, TaskConfig
from reverse_collector.plugin import ApiCollectorPlugin, PageResult
from reverse_collector.registry import register_plugin


@register_plugin("demo")
class DemoPlugin(ApiCollectorPlugin):
    """Small public-JSON example used to verify a fresh installation."""

    description = "Paginated JSON API example (no authentication)"

    async def first_request(
        self,
        context: RunContext,
        task: TaskConfig,
        checkpoint: dict[str, Any] | None,
    ) -> RequestSpec:
        page = int((checkpoint or {}).get("next_page", 1))
        return self._request(task, page)

    def _request(self, task: TaskConfig, page: int) -> RequestSpec:
        base_url = str(
            task.parameters.get("base_url", "https://jsonplaceholder.typicode.com/posts")
        )
        page_size = int(task.parameters.get("page_size", 20))
        return RequestSpec(
            endpoint_id="demo.posts",
            method="GET",
            url=base_url,
            params={"_page": page, "_limit": page_size},
            metadata={"expect_json": True},
        )

    async def parse_page(
        self,
        context: RunContext,
        task: TaskConfig,
        request: RequestSpec,
        response: ResponseData,
    ) -> PageResult:
        payload = response.json()
        if not isinstance(payload, list):
            raise PluginError("demo response schema changed: expected a JSON list")
        records = [item for item in payload if isinstance(item, dict)]
        if len(records) != len(payload):
            raise PluginError("demo response contains a non-object record")
        page = int(dict(request.params)["_page"])
        page_size = int(dict(request.params)["_limit"])
        done = len(records) < page_size
        next_page = page + 1
        return PageResult(
            records=records,
            next_request=None if done else self._request(task, next_page),
            checkpoint={"next_page": next_page},
            done=done,
        )

