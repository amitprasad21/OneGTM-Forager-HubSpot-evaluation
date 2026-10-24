import asyncio

import pytest

from app.clients.forager import ForagerAuthError, ForagerError
from app.clients.hubspot import HubSpotError
from app.credits import CreditBudgetExceeded
from app.jobs import JobStore
from app.worker import Worker


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeAutomation:
    def __init__(self):
        self.calls = []
        self.failed = []
        self.errors: list[Exception] = []

    async def company_created(self, company_id, force=False):
        return self._run("company", company_id)

    async def contact_created(self, contact_id, force=False):
        return self._run("contact", contact_id)

    def _run(self, kind, object_id):
        self.calls.append((kind, object_id))
        if self.errors:
            raise self.errors.pop(0)
        return {"ok": True}

    async def mark_failed(self, object_type, object_id, error):
        self.failed.append((object_type, object_id, error))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    store = JobStore(str(tmp_path / "app.db"), clock=clock)
    yield store
    store.close()


@pytest.fixture
def automation():
    return FakeAutomation()


@pytest.fixture
def worker(store, automation):
    return Worker(store, automation, max_attempts=3, retry_delays=(30, 120))


async def test_runs_jobs_by_kind(worker, store, automation):
    store.enqueue("company_created", "101")
    store.enqueue("contact_created", "5")

    assert await worker.run_once() is True
    assert await worker.run_once() is True
    assert await worker.run_once() is False

    assert automation.calls == [("company", "101"), ("contact", "5")]
    assert store.counts()["done"] == 2


async def test_transient_error_is_retried_with_backoff(worker, store, automation, clock):
    automation.errors = [ForagerError("Forager failed with HTTP 500", 500)]
    job_id = store.enqueue("contact_created", "5")

    await worker.run_once()
    assert store.get(job_id).status == "queued"
    assert await worker.run_once() is False  # waiting for the 30 s backoff

    clock.now += 31
    await worker.run_once()
    assert store.get(job_id).status == "done"
    assert automation.failed == []


async def test_exhausted_retries_mark_record_failed(worker, store, automation, clock):
    automation.errors = [ForagerError("HTTP 500", 500)] * 3
    job_id = store.enqueue("contact_created", "5")

    for _ in range(3):
        await worker.run_once()
        clock.now += 200

    assert store.get(job_id).status == "failed"
    assert automation.failed == [("contact", "5", "HTTP 500")]


@pytest.mark.parametrize(
    "error",
    [
        ForagerAuthError("bad key", 401),
        CreditBudgetExceeded("budget"),
        HubSpotError("validation", 400, "VALIDATION_ERROR"),
        ForagerError("bad request", 400),
    ],
)
async def test_non_retryable_errors_fail_immediately(worker, store, automation, error):
    automation.errors = [error]
    job_id = store.enqueue("company_created", "101")

    await worker.run_once()

    assert store.get(job_id).status == "failed"
    assert automation.failed[0][:2] == ("company", "101")


async def test_rate_limited_hubspot_error_is_retried(worker, store, automation):
    automation.errors = [HubSpotError("rate", 429, "RATE_LIMITS")]
    job_id = store.enqueue("company_created", "101")

    await worker.run_once()

    assert store.get(job_id).status == "queued"


async def test_mark_failed_errors_do_not_crash_worker(worker, store, automation):
    async def broken(*args):
        raise RuntimeError("hubspot down")

    automation.mark_failed = broken
    automation.errors = [ForagerAuthError("bad key", 401)]
    store.enqueue("company_created", "101")

    assert await worker.run_once() is True


async def test_run_forever_stops_on_event(store, automation):
    worker = Worker(store, automation, poll_interval=0.01)
    store.enqueue("contact_created", "5")
    stop = asyncio.Event()

    task = asyncio.create_task(worker.run_forever(stop))
    for _ in range(100):
        if automation.calls:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert automation.calls == [("contact", "5")]
