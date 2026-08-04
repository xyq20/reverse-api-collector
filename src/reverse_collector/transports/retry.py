from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from reverse_collector.errors import HttpStatusError, NetworkError, RateLimitError
from reverse_collector.models import RequestSpec, ResponseData, RetryConfig
from reverse_collector.transports.base import Transport


async def send_with_retry(
    transport: Transport,
    request: RequestSpec,
    config: RetryConfig,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> ResponseData:
    last_error: Exception | None = None
    for attempt in range(1, config.attempts + 1):
        try:
            return await transport.send(request)
        except asyncio.CancelledError:
            raise
        except RateLimitError as exc:
            last_error = exc
            retryable = request.may_retry
            retry_after = exc.retry_after
        except NetworkError as exc:
            last_error = exc
            retryable = request.may_retry
            retry_after = None
        except HttpStatusError as exc:
            last_error = exc
            retryable = request.may_retry and exc.status_code in config.retry_statuses
            retry_after = None
        if not retryable or attempt >= config.attempts:
            raise last_error
        base = min(config.max_delay, config.base_delay * (2 ** (attempt - 1)))
        delay = retry_after if retry_after is not None else base
        if config.jitter:
            delay += delay * config.jitter * random_value()
        await sleep(delay)
    assert last_error is not None
    raise last_error

