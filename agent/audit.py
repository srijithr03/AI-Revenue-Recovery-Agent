"""L7 -- Audit trail.

An append-only event log, per case. The bar it is built to clear: a judge who
opens any case ID must be able to reconstruct what the system knew, what it
considered, what it chose, why, what policy said, what it did, and what
happened -- without asking a question.

Append-only is enforced, not just intended: there is no method here that
mutates or removes an existing event.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))

# Event types, in roughly the order a case moves through them.
DIAGNOSED = "DIAGNOSED"
SCORED = "SCORED"
PLANNED = "PLANNED"
POLICY_CHECKED = "POLICY_CHECKED"
EXECUTING = "EXECUTING"
WAITING = "WAITING"
OUTCOME_CHECK = "OUTCOME_CHECK"
RECOVERED = "RECOVERED"
STOPPED = "STOPPED"
ESCALATED = "ESCALATED"
INELIGIBLE = "INELIGIBLE"
DEFERRED = "DEFERRED"

# Who produced the event. `llm` appears only on DIAGNOSED, which is the only
# place a language model is consulted at all.
ACTORS = ("rules", "llm", "policy", "executor", "verifier", "allocator")


@dataclass
class AuditEvent:
    timestamp: str          # millisecond precision, IST
    event: str
    actor: str
    detail: str
    state: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "actor": self.actor,
            "detail": self.detail,
            "state": self.state,
            "payload": self.payload,
        }


class AuditTrail:
    """One trail per batch, indexed by case id."""

    def __init__(self, clock_start: datetime | None = None) -> None:
        self._events: dict[str, list[AuditEvent]] = {}
        self._t0 = time.perf_counter()
        # A wall clock that advances with real elapsed processing time, so the
        # timestamps in the log are genuine millisecond offsets from the start
        # of the run rather than decoration.
        self._clock_start = clock_start or datetime.now(IST)

    def _now(self) -> str:
        elapsed = time.perf_counter() - self._t0
        return (self._clock_start + timedelta(seconds=elapsed)).strftime(
            "%Y-%m-%d %H:%M:%S.") + f"{int((elapsed % 1) * 1000):03d}"

    def append(self, case_id: str, event: str, actor: str, detail: str,
               state: str, payload: dict[str, Any] | None = None) -> AuditEvent:
        ev = AuditEvent(timestamp=self._now(), event=event, actor=actor,
                        detail=detail, state=state, payload=payload or {})
        self._events.setdefault(case_id, []).append(ev)
        return ev

    def events(self, case_id: str) -> list[AuditEvent]:
        return list(self._events.get(case_id, []))

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {cid: [e.to_dict() for e in evs] for cid, evs in self._events.items()}

    def __len__(self) -> int:
        return sum(len(v) for v in self._events.values())
