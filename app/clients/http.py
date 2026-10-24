"""HTTP helpers shared by the API clients: timeouts, bounded retries, backoff."""

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

Sleep = Callable[[float], Awaitable[None]]


def build_client(base_url: str, headers: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=DEFAULT_TIMEOUT)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form is not used by these APIs; fall back to backoff.


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    sleep: Sleep = asyncio.sleep,
    **kwargs,
) -> httpx.Response:
    """Send a request, retrying transient failures (429, 5xx, timeouts, connection errors).

    The final response is returned even if it is an error status, so callers
    decide how to interpret it; the final transport exception is re-raised.
    """
    for attempt in range(1, max_attempts + 1):
        is_last = attempt == max_attempts
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError:
            if is_last:
                raise
            await sleep(_backoff(attempt, base_delay, max_delay))
            continue

        if response.status_code not in RETRYABLE_STATUS or is_last:
            return response

        delay = _retry_after_seconds(response)
        await sleep(min(delay, max_delay) if delay is not None else _backoff(attempt, base_delay, max_delay))

    raise AssertionError("unreachable")


def _backoff(attempt: int, base_delay: float, max_delay: float) -> float:
    return min(max_delay, base_delay * 2 ** (attempt - 1) + random.uniform(0, base_delay / 2))
