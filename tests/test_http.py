import httpx
import pytest
import respx

from app.clients.http import request_with_retry

URL = "https://api.example.test/thing"


class FakeSleep:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


@pytest.fixture
def sleep():
    return FakeSleep()


@respx.mock
async def test_returns_first_successful_response(sleep):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(client, "GET", URL, sleep=sleep)

    assert response.status_code == 200
    assert route.call_count == 1
    assert sleep.calls == []


@respx.mock
async def test_retries_429_honouring_retry_after(sleep):
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={}),
        ]
    )

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(client, "GET", URL, sleep=sleep)

    assert response.status_code == 200
    assert route.call_count == 2
    assert sleep.calls == [7.0]


@respx.mock
async def test_retry_after_is_capped(sleep):
    respx.get(URL).mock(
        side_effect=[httpx.Response(503, headers={"Retry-After": "3600"}), httpx.Response(200)]
    )

    async with httpx.AsyncClient() as client:
        await request_with_retry(client, "GET", URL, sleep=sleep, max_delay=30)

    assert sleep.calls == [30]


@respx.mock
async def test_5xx_retried_until_attempts_exhausted_then_returned(sleep):
    route = respx.get(URL).mock(return_value=httpx.Response(502))

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(client, "GET", URL, sleep=sleep, max_attempts=3)

    assert response.status_code == 502
    assert route.call_count == 3
    assert len(sleep.calls) == 2
    assert sleep.calls[1] > sleep.calls[0]  # exponential backoff


@respx.mock
async def test_4xx_other_than_429_is_not_retried(sleep):
    route = respx.get(URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(client, "GET", URL, sleep=sleep)

    assert response.status_code == 400
    assert route.call_count == 1


@respx.mock
async def test_timeouts_retried_then_raised(sleep):
    route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ReadTimeout):
            await request_with_retry(client, "GET", URL, sleep=sleep, max_attempts=2)

    assert route.call_count == 2


@respx.mock
async def test_transport_error_then_success(sleep):
    respx.post(URL).mock(side_effect=[httpx.ConnectError("reset"), httpx.Response(201)])

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(client, "POST", URL, sleep=sleep, json={"a": 1})

    assert response.status_code == 201
