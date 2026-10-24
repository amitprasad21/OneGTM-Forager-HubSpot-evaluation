import pytest

from app.credits import CreditBudgetExceeded
from app.jobs import JobStore, SqliteCreditLedger


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    store = JobStore(str(tmp_path / "nested" / "app.db"), clock=clock)
    yield store
    store.close()


def test_record_event_is_true_only_the_first_time(store):
    assert store.record_event("evt-1") is True
    assert store.record_event("evt-1") is False
    assert store.record_event("evt-2") is True


def test_enqueue_and_claim_in_fifo_order(store):
    first = store.enqueue("company_created", "101")
    second = store.enqueue("contact_created", "5")

    job = store.claim_next()

    assert job.id == first and job.kind == "company_created" and job.object_id == "101"
    assert job.attempts == 1
    assert store.claim_next().id == second
    assert store.claim_next() is None


def test_duplicate_active_job_is_not_enqueued_twice(store):
    assert store.enqueue("contact_created", "5") is not None
    assert store.enqueue("contact_created", "5") is None

    job = store.claim_next()
    assert store.enqueue("contact_created", "5") is None  # still running

    store.complete(job.id)
    assert store.enqueue("contact_created", "5") is not None  # finished jobs don't block


def test_failed_job_is_retried_after_delay(store, clock):
    store.enqueue("contact_created", "5")
    job = store.claim_next()

    final = store.fail(job.id, "boom", retry_delay=30, max_attempts=3)

    assert final is False
    assert store.claim_next() is None  # not due yet
    clock.now += 31
    retried = store.claim_next()
    assert retried.id == job.id and retried.attempts == 2


def test_job_fails_permanently_after_max_attempts(store, clock):
    store.enqueue("contact_created", "5")
    for _ in range(3):
        job = store.claim_next()
        final = store.fail(job.id, "boom", retry_delay=0, max_attempts=3)

    assert final is True
    assert store.claim_next() is None
    assert store.get(job.id).status == "failed"
    assert store.get(job.id).last_error == "boom"


def test_non_retryable_failure_is_final_immediately(store):
    store.enqueue("contact_created", "5")
    job = store.claim_next()

    assert store.fail(job.id, "auth", retry_delay=None, max_attempts=3) is True
    assert store.get(job.id).status == "failed"


def test_stale_running_jobs_are_requeued(store, clock):
    store.enqueue("company_created", "101")
    job = store.claim_next()
    clock.now += 600

    assert store.requeue_stale(lease_seconds=300) == 1
    assert store.claim_next().id == job.id


def test_counts_and_recent_jobs(store):
    store.enqueue("company_created", "101")
    store.enqueue("contact_created", "5")
    store.complete(store.claim_next().id)

    assert store.counts() == {"queued": 1, "running": 0, "done": 1, "failed": 0}
    assert [j.object_id for j in store.recent(limit=10)] == ["5", "101"]


def test_store_survives_reopen(tmp_path, clock):
    path = str(tmp_path / "app.db")
    store = JobStore(path, clock=clock)
    store.enqueue("contact_created", "5")
    store.record_event("evt-1")
    store.close()

    reopened = JobStore(path, clock=clock)
    assert reopened.record_event("evt-1") is False
    assert reopened.claim_next().object_id == "5"
    reopened.close()


def test_ping(store):
    assert store.ping() is True


# --- persistent credit ledger ------------------------------------------------

def test_sqlite_ledger_persists_spend_and_guards_budget(store):
    ledger = SqliteCreditLedger(store, budget=20)
    ledger.record(15, "phone")
    ledger.record(0, "poll")

    assert ledger.spent == 15
    assert SqliteCreditLedger(store, budget=20).spent == 15  # shared via the database
    ledger.ensure_available(5)
    with pytest.raises(CreditBudgetExceeded):
        ledger.ensure_available(6)


def test_sqlite_ledger_summary(store):
    ledger = SqliteCreditLedger(store, budget=45)
    ledger.record(1, "organization_search")
    ledger.record(5, "work_email")
    ledger.record(5, "work_email")

    assert ledger.summary() == {
        "budget": 45,
        "spent": 11,
        "remaining": 34,
        "by_operation": {"organization_search": 1, "work_email": 10},
    }
