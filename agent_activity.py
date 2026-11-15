"""Bounded run identity and server-authored progress; never stream model reasoning."""
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic
from uuid import uuid4


class RunCancelled(Exception):
    pass


class TransientSourceError(OSError):
    """Sanitized transport/rate-limit failure eligible for one bounded retry."""


class Activity:
    def __init__(self, emit=None, *, seconds=180, current=None):
        self.id = uuid4().hex
        self.cancelled = Event()
        self.deadline = monotonic() + seconds
        self.emit = emit or (lambda event: None)
        self.lock = Lock()
        self.sequence = 0
        self.current = current

    def check(self):
        if self.cancelled.is_set() or monotonic() > self.deadline or self.current and not self.current():
            raise RunCancelled("Analysis canceled or time budget reached.")

    def event(self, specialist, stage, status, summary, *, facts=None):
        self.check()
        with self.lock:
            self.check()
            self.sequence += 1
            event = dict(type="activity", run_id=self.id, sequence=self.sequence,
                         at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                         specialist=specialist, stage=stage, status=status, summary=summary)
            if facts is not None:
                event["facts"] = facts
                event["fact_ids"] = [f["id"] for f in facts]
            try:
                self.emit(event)
            except (OSError, BrokenPipeError, ConnectionError):
                self.cancelled.set()
                raise RunCancelled("Client disconnected.") from None
