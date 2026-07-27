"""
Handles `/enable <delay>` and `/disable <delay>` by scheduling a one-shot
job via APScheduler. Also used for the 30-second /panic confirmation
window.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

_DELAY_RE = re.compile(r"^(\d+)([mh])$", re.IGNORECASE)


class InvalidDelayError(ValueError):
    pass


def parse_delay(delay_str: str) -> timedelta:
    """Parse a delay string like '30m' or '2h' into a timedelta."""
    match = _DELAY_RE.match(delay_str.strip())
    if not match:
        raise InvalidDelayError(f"Invalid delay '{delay_str}', expected e.g. '30m' or '2h'")
    amount, unit = int(match.group(1)), match.group(2).lower()
    return timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount)


class DelayScheduler:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    def schedule_once(self, coro_factory, delay: timedelta, job_id: str) -> None:
        """Schedule `coro_factory()` (a zero-arg callable returning a
        coroutine) to run once after `delay`. `job_id` lets a caller replace
        a previously-scheduled job of the same kind (e.g. a second /enable
        before the first fires)."""
        run_date = datetime.now(timezone.utc) + delay
        self._scheduler.add_job(
            coro_factory,
            trigger=DateTrigger(run_date=run_date),
            id=job_id,
            replace_existing=True,
        )

    def cancel(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001 - job may not exist, that's fine
            pass
