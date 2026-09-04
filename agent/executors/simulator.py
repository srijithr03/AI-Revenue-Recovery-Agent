"""Simulator execution adapter.

Used for the full batch, because Razorpay test mode cannot reproduce recovery
dynamics that play out over hours -- it will never simulate "the retry
succeeded 40 minutes later because the customer's salary landed".

This module is part of L0, not the agent. It is one of only two places in the
codebase permitted to read ``data/ground_truth.json``.

HOW OUTCOMES ARE SAMPLED
------------------------
Naively drawing an independent Bernoulli per attempt would let three retries
turn a 30% action into a 66% one, which would flatter any strategy that simply
does more. Instead:

  * One uniform draw ``u`` is taken per case, at the start. It represents that
    customer's latent willingness to come back.
  * Each executed action contributes an odds MULTIPLIER, recovered from the
    ground truth as ``odds(p_treated[a]) / odds(p_natural)``. This is the same
    scale the generator composed on.
  * Repeated attempts of the same retry action contribute a fractional power of
    that multiplier, so three attempts earn the full effect and one attempt
    earns a third of it, on the log-odds scale.
  * Repeated identical contacts contribute nothing extra. Sending the same SMS
    twice does not double its effect.
  * The case recovers at the first step where the accumulated probability
    exceeds ``u``.

Multipliers below 1.0 -- retrying an empty balance, messaging an
annoyance-prone customer -- push the accumulated probability DOWN. A strategy
that acts indiscriminately is therefore genuinely punished, which is what makes
the naive arm an honest opponent rather than a strawman.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from agent.constants import CONTACT_ACTIONS, RETRY_ACTIONS

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

RETRY_ATTEMPT_CAP = 3  # attempts that earn the full retry multiplier


@dataclass
class ExecutionResult:
    success: bool
    request_id: str
    latency_ms: float
    mode: str                 # "simulated" | "razorpay_test"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "request_id": self.request_id,
            "latency_ms": round(self.latency_ms, 2),
            "mode": self.mode,
            "detail": self.detail,
        }


def _odds(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return p / (1 - p)


class SimulatorExecutor:
    mode = "simulated"

    def __init__(self, truth: dict[str, Any] | None = None, seed: int = 0) -> None:
        if truth is None:
            with open(os.path.join(DATA, "ground_truth.json")) as fh:
                truth = json.load(fh)
        self.truth = truth
        self.rng = np.random.default_rng(seed)
        self._u: dict[str, float] = {}
        self._applied: dict[str, dict[str, int]] = {}
        self._req = 0

    # ---------------------------------------------------------------- per-case

    def begin_case(self, case_id: str) -> None:
        """Draw the latent willingness for this case, once."""
        self._u[case_id] = float(self.rng.random())
        self._applied[case_id] = {}

    def _multiplier(self, case_id: str, action: str) -> float:
        t = self.truth[case_id]
        return _odds(t["p_treated"][action]) / _odds(t["p_natural"])

    def current_probability(self, case_id: str) -> float:
        """Accumulated recovery probability given everything executed so far."""
        t = self.truth[case_id]
        odds = _odds(t["p_natural"])
        for action, n in self._applied.get(case_id, {}).items():
            m = self._multiplier(case_id, action)
            if action in RETRY_ACTIONS:
                power = min(n, RETRY_ATTEMPT_CAP) / RETRY_ATTEMPT_CAP
            else:
                power = 1.0 if n >= 1 else 0.0
            odds *= m ** power
        return odds / (1.0 + odds)

    # ---------------------------------------------------------------- execute

    def execute(self, case: dict[str, Any], action: str) -> ExecutionResult:
        cid = case["case_id"]
        if cid not in self._u:
            self.begin_case(cid)

        t0 = time.perf_counter()
        self._applied[cid][action] = self._applied[cid].get(action, 0) + 1
        p = self.current_probability(cid)
        success = self._u[cid] < p

        self._req += 1
        rid = f"sim_{self._req:07d}"
        latency = (time.perf_counter() - t0) * 1000.0

        return ExecutionResult(
            success=success,
            request_id=rid,
            latency_ms=latency,
            mode=self.mode,
            detail=f"p={p:.4f} u={self._u[cid]:.4f}",
        )

    def observe_no_action(self, case: dict[str, Any]) -> ExecutionResult:
        """The control path: sample the counterfactual with nothing done."""
        cid = case["case_id"]
        if cid not in self._u:
            self.begin_case(cid)
        p = self.truth[cid]["p_natural"]
        return ExecutionResult(
            success=self._u[cid] < p,
            request_id="none",
            latency_ms=0.0,
            mode=self.mode,
            detail=f"p_natural={p:.4f} u={self._u[cid]:.4f}",
        )
