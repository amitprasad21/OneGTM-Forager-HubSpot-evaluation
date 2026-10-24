"""Background worker: runs queued enrichment jobs with bounded retries."""

import asyncio

from app.clients.forager import ForagerAuthError, ForagerError
from app.clients.hubspot import HubSpotError
from app.credits import CreditBudgetExceeded
from app.jobs import Job, JobStore
from app.log import get_logger, log_event

log = get_logger(__name__)

KIND_OBJECT_TYPES = {"company_created": "company", "contact_created": "contact"}


def is_retryable(error: Exception) -> bool:
    if isinstance(error, (ForagerAuthError, CreditBudgetExceeded)):
        return False
    status = getattr(error, "status_code", None)
    if isinstance(error, (ForagerError, HubSpotError)) and status is not None:
        return status == 429 or status >= 500
    return True  # timeouts, connection errors, unexpected failures


class Worker:
    def __init__(
        self,
        store: JobStore,
        automation,
        *,
        max_attempts: int = 3,
        retry_delays: tuple[float, ...] = (30, 120),
        poll_interval: float = 1.0,
    ):
        self._store = store
        self._automation = automation
        self._max_attempts = max_attempts
        self._retry_delays = retry_delays
        self._poll_interval = poll_interval

    async def run_once(self) -> bool:
        """Run the next due job; returns False when nothing was due."""
        job = self._store.claim_next()
        if job is None:
            return False
        object_type = KIND_OBJECT_TYPES.get(job.kind)
        log_event(log, "job.started", job_id=job.id, kind=job.kind, object_id=job.object_id, attempt=job.attempts)
        try:
            if object_type == "company":
                result = await self._automation.company_created(job.object_id)
            elif object_type == "contact":
                result = await self._automation.contact_created(job.object_id)
            else:
                raise ValueError(f"unknown job kind {job.kind!r}")
        except Exception as error:  # noqa: BLE001 - every failure must be recorded
            await self._handle_failure(job, object_type, error)
            return True
        self._store.complete(job.id)
        log_event(log, "job.done", job_id=job.id, kind=job.kind, result=result)
        return True

    async def run_forever(self, stop: asyncio.Event) -> None:
        log_event(log, "worker.started")
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("worker.loop_error")
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
        log_event(log, "worker.stopped")

    async def _handle_failure(self, job: Job, object_type: str | None, error: Exception) -> None:
        message = str(error) or type(error).__name__
        delay = None
        if is_retryable(error):
            delay = self._retry_delays[min(job.attempts - 1, len(self._retry_delays) - 1)]
        final = self._store.fail(job.id, message, retry_delay=delay, max_attempts=self._max_attempts)
        log_event(
            log,
            "job.failed" if final else "job.retry_scheduled",
            job_id=job.id,
            kind=job.kind,
            error_type=type(error).__name__,
            error=message,
            retry_in=None if final else delay,
        )
        if final and object_type:
            try:
                await self._automation.mark_failed(object_type, job.object_id, message)
            except Exception:  # noqa: BLE001
                log.exception("job.mark_failed_error")
