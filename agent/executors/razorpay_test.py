"""Razorpay test-mode execution adapter.

Purpose: demonstrate that the action layer talks to a real payments API, with
real request IDs and real latencies, rather than only to a simulator.

Scope, stated plainly: this adapter is used for a small, DISCLOSED subset of
cases. It cannot be used for the whole batch, because test mode cannot
reproduce recovery dynamics that unfold over hours -- there is no test-mode
customer who tops up their balance and retries at 9am. Every case record
carries an ``execution_mode`` field so the split is visible per case, in the
UI, and in the results artifacts.

Credentials come from RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET. If they are absent
the adapter reports itself unavailable and the harness runs the whole batch
through the simulator, which is the designed degradation rather than an error.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from agent.executors.simulator import ExecutionResult


class RazorpayTestExecutor:
    """Live test-mode calls, with a hard fallback to unavailable."""

    mode = "razorpay_test"

    def __init__(self) -> None:
        self.client = None
        self.available = False
        self.unavailable_reason = "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set"

        key_id = os.environ.get("RAZORPAY_KEY_ID")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
        if not (key_id and key_secret):
            return
        if not key_id.startswith("rzp_test_"):
            # Refuse to touch anything that is not explicitly a test key.
            self.unavailable_reason = "RAZORPAY_KEY_ID is not a rzp_test_ key; refusing"
            return
        try:
            import razorpay
            self.client = razorpay.Client(auth=(key_id, key_secret))
            self.client.set_app_details({"title": "recovery-agent", "version": "1.0"})
            self.available = True
            self.unavailable_reason = ""
        except Exception as exc:  # noqa: BLE001 - construction must not raise
            self.unavailable_reason = f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------ calls

    def execute(self, case: dict[str, Any], action: str) -> ExecutionResult:
        """Issue a genuine test-mode API call for the given action.

        Retries create a real Order; contact actions create a real Payment Link.
        Neither moves money -- test mode never does -- but both produce a real
        Razorpay object id and a real round-trip latency, which is the point.
        """
        if not self.available or self.client is None:
            return ExecutionResult(
                success=False, request_id="unavailable", latency_ms=0.0,
                mode=self.mode,
                detail=f"adapter unavailable: {self.unavailable_reason}")

        t0 = time.perf_counter()
        amount_paise = int(round(float(case["amount"]) * 100))
        ref = f"{case['case_id']}-{uuid.uuid4().hex[:8]}"

        try:
            if action in ("retry_immediate", "retry_delayed"):
                obj = self.client.order.create({
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": ref,
                    "notes": {"case_id": case["case_id"], "action": action,
                              "source": "recovery-agent"},
                })
                rid = obj.get("id", "unknown")
                detail = f"order {rid} status={obj.get('status')}"
            else:
                obj = self.client.payment_link.create({
                    "amount": amount_paise,
                    "currency": "INR",
                    "accept_partial": False,
                    "reference_id": ref,
                    "description": f"Payment retry for {case['case_id']}",
                    "notify": {"sms": False, "email": False},
                    "reminder_enable": False,
                    "notes": {"case_id": case["case_id"], "action": action,
                              "source": "recovery-agent"},
                })
                rid = obj.get("id", "unknown")
                detail = f"payment_link {rid} status={obj.get('status')}"

            latency = (time.perf_counter() - t0) * 1000.0
            # A created object is a successful API call. It is NOT a recovered
            # payment -- L6 keeps those two ideas apart, and nothing here is
            # permitted to claim recovery.
            return ExecutionResult(success=False, request_id=rid,
                                   latency_ms=latency, mode=self.mode,
                                   detail=detail)

        except Exception as exc:  # noqa: BLE001
            latency = (time.perf_counter() - t0) * 1000.0
            return ExecutionResult(
                success=False, request_id="error", latency_ms=latency,
                mode=self.mode, detail=f"{type(exc).__name__}: {str(exc)[:200]}")
