"""L5 -- State machine and bounded execution.

Transitions are ENUMERATED. Any transition not in the table raises. That is what
makes "bounded" a property of the system rather than a claim about it: the agent
cannot invent a sequence, no matter what any upstream component proposes.

The other thing that lives here is SEQUENTIAL ESCALATION, and it is the reason
this layer is not a for-loop.

A naive retry bot retries three times AND THEN contacts the customer. An agent
that commits to a single action type is doing structurally less work, and will
lose to that bot for reasons that have nothing to do with how well it targets.
So when free retries are exhausted, the standby contact candidate attached at
allocation time is reconsidered: a contact that was not worth its annoyance cost
while a free retry remained may well be worth it now that the free option is
spent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent import audit as ev
from agent.audit import AuditTrail
from agent.constants import CONTACT_ACTIONS
from agent.policy import ALLOW, BLOCK, ESCALATE, PolicyContext, PolicyEngine
from agent.valuation import Plan, action_cost
from agent.verification import OBSERVATION_WINDOW_HOURS, verify

# ---------------------------------------------------------------------------
# Enumerated transitions.  Nothing else is legal.
# ---------------------------------------------------------------------------

TRANSITIONS: dict[str, frozenset[str]] = {
    "FAILED": frozenset({"DIAGNOSED"}),
    "DIAGNOSED": frozenset({"SCORED"}),
    "SCORED": frozenset({"ELIGIBLE", "INELIGIBLE"}),
    "ELIGIBLE": frozenset({"POLICY_CHECKED"}),
    "POLICY_CHECKED": frozenset({"APPROVED", "ESCALATED", "BLOCKED"}),
    "APPROVED": frozenset({"EXECUTING"}),
    "EXECUTING": frozenset({"WAITING"}),
    "WAITING": frozenset({"OUTCOME_CHECK"}),
    "OUTCOME_CHECK": frozenset({"RECOVERED", "RETRYABLE", "STOPPED"}),
    "RETRYABLE": frozenset({"POLICY_CHECKED"}),
    "BLOCKED": frozenset({"STOPPED"}),
    # terminal
    "RECOVERED": frozenset(),
    "STOPPED": frozenset(),
    "ESCALATED": frozenset(),
    "INELIGIBLE": frozenset(),
}

TERMINAL = frozenset({"RECOVERED", "STOPPED", "ESCALATED", "INELIGIBLE"})


class IllegalTransition(RuntimeError):
    pass


# ---------------------------------------------------------------------------

@dataclass
class BudgetTracker:
    """Batch-level contact budget, shared across every case in an arm."""
    budget: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(self.budget - self.used, 0)

    def take(self, n: int = 1) -> bool:
        if self.used + n > self.budget:
            return False
        self.used += n
        return True


@dataclass
class CaseOutcome:
    case_id: str
    arm: str
    state: str = "FAILED"
    attempts: int = 0
    contacts: int = 0
    action_sequence: list[str] = field(default_factory=list)
    attempted: bool = False
    payment_success: bool = False
    confirmed: bool = False
    amount_confirmed: float = 0.0
    cost_spent: float = 0.0
    stop_reason: str = ""
    execution_mode: str = "simulated"
    deferrals: int = 0
    escalated_sequentially: bool = False
    hours_elapsed: float = 0.0
    request_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "arm": self.arm,
            "state": self.state,
            "attempts": self.attempts,
            "contacts": self.contacts,
            "action_sequence": self.action_sequence,
            "attempted": self.attempted,
            "payment_success": self.payment_success,
            "confirmed": self.confirmed,
            "amount_confirmed": round(self.amount_confirmed, 2),
            "cost_spent": round(self.cost_spent, 2),
            "stop_reason": self.stop_reason,
            "execution_mode": self.execution_mode,
            "deferrals": self.deferrals,
            "escalated_sequentially": self.escalated_sequentially,
            "hours_elapsed": round(self.hours_elapsed, 2),
            "request_ids": self.request_ids,
        }


class StateMachine:
    def __init__(self, engine: PolicyEngine, executor: Any, trail: AuditTrail,
                 budget: BudgetTracker, annoyance_cost: float,
                 respect_budget: bool = True) -> None:
        self.engine = engine
        self.executor = executor
        self.trail = trail
        self.budget = budget
        self.annoyance_cost = annoyance_cost
        self.respect_budget = respect_budget

    # ---------------------------------------------------------------- helpers

    def _go(self, out: CaseOutcome, to: str) -> None:
        allowed = TRANSITIONS.get(out.state, frozenset())
        if to not in allowed:
            raise IllegalTransition(
                f"{out.case_id}: {out.state} -> {to} is not an enumerated "
                f"transition (legal: {sorted(allowed)})")
        out.state = to

    def _charge(self, out: CaseOutcome, action: str) -> None:
        out.cost_spent += action_cost(action, self.annoyance_cost)

    # ---------------------------------------------------------------- run

    def run_case(self, case: dict[str, Any], diagnosis: Any, plan: Plan,
                 arm: str) -> CaseOutcome:
        cid = case["case_id"]
        out = CaseOutcome(case_id=cid, arm=arm,
                          execution_mode=getattr(self.executor, "mode", "simulated"))

        self.trail.append(cid, ev.DIAGNOSED, "llm" if diagnosis.path.startswith(("llm", "fallback"))
                          else "rules",
                          f"{diagnosis.failure_class} at confidence {diagnosis.confidence:.2f} "
                          f"via {diagnosis.path}", "DIAGNOSED",
                          {"signals": diagnosis.signals, "path": diagnosis.path,
                           "llm_error": diagnosis.llm_error})
        self._go(out, "DIAGNOSED")

        self.trail.append(cid, ev.SCORED, "allocator",
                          f"p_natural {plan.p_natural:.3f}, segment {plan.segment}",
                          "SCORED", {"segment": plan.segment})
        self._go(out, "SCORED")

        # ---- eligibility ---------------------------------------------------
        if plan.action == "no_action":
            self._go(out, "INELIGIBLE")
            out.stop_reason = self._skip_reason(plan)
            self.trail.append(cid, ev.INELIGIBLE, "allocator", out.stop_reason,
                              "INELIGIBLE", {"best_ev": plan.incremental_ev})
            self._settle(case, out)
            return out

        self._go(out, "ELIGIBLE")
        self.trail.append(cid, ev.PLANNED, "allocator",
                          f"selected {plan.action}, incremental EV "
                          f"{plan.incremental_ev:.2f}", "ELIGIBLE",
                          {"budget_rank": plan.budget_rank,
                           "budget_contenders": plan.budget_contenders,
                           "escalation_standby": plan.escalation_action})

        # ---- the bounded loop ----------------------------------------------
        action = plan.action
        elapsed_h = 0.0
        escalation_used = False
        full_rules_logged = False

        while True:
            self._go(out, "POLICY_CHECKED")
            intended_hour = int((int(case.get("hour", 12)) + elapsed_h) % 24)
            ctx = PolicyContext(
                attempts_used=out.attempts,
                contacts_used_case=out.contacts,
                contacts_used_batch=self.budget.used,
                intended_hour=intended_hour,
                incremental_ev=plan.incremental_ev,
            )
            decision = self.engine.evaluate(case, action, ctx)

            # The full eight-rule trace is logged on the first check and on any
            # check that is not clean. Repeat clean checks store counts only --
            # the trace is identical, and repeating it inflated the audit
            # artifact roughly fourfold for no added information.
            interesting = (not full_rules_logged or decision.outcome != ALLOW
                           or decision.deferred)
            payload = {"blocked_by": decision.blocked_by,
                       "deferred": decision.deferred,
                       "deferred_to_hour": decision.deferred_to_hour,
                       "rules_evaluated": decision.rules_evaluated,
                       "rules_applicable": decision.rules_applicable,
                       "violations": [r.rule_id for r in decision.violations]}
            if interesting:
                payload["rules"] = [r.to_dict() for r in decision.rules]
                full_rules_logged = True
            self.trail.append(
                cid, ev.POLICY_CHECKED, "policy",
                f"{decision.outcome} for {action}; "
                f"{decision.rules_evaluated} rules evaluated, "
                f"{len(decision.violations)} violations", "POLICY_CHECKED",
                payload)

            if decision.outcome == BLOCK:
                self._go(out, "BLOCKED")
                self._go(out, "STOPPED")
                out.stop_reason = f"policy {decision.blocked_by}: {decision.block_detail}"
                self.trail.append(cid, ev.STOPPED, "policy", out.stop_reason, "STOPPED")
                break

            if decision.outcome == ESCALATE:
                self._go(out, "ESCALATED")
                out.stop_reason = decision.escalation_reason
                self.trail.append(cid, ev.ESCALATED, "policy",
                                  decision.escalation_reason, "ESCALATED")
                break

            # Quiet hours DEFER, never cancel.
            if decision.deferred:
                out.deferrals += 1
                target = decision.deferred_to_hour or 9
                wait = (target - intended_hour) % 24
                elapsed_h += wait
                self.trail.append(
                    cid, ev.DEFERRED, "policy",
                    f"contact deferred {wait}h from {intended_hour:02d}:00 to "
                    f"{target:02d}:00 IST", "POLICY_CHECKED",
                    {"wait_hours": wait})

            # Batch contact budget is a hard stop for contact actions.
            is_contact = action in CONTACT_ACTIONS
            if is_contact and self.respect_budget and not self.budget.take(1):
                self._go(out, "APPROVED")
                self._go(out, "EXECUTING")
                self._go(out, "WAITING")
                self._go(out, "OUTCOME_CHECK")
                self._go(out, "STOPPED")
                out.stop_reason = (f"batch contact budget exhausted "
                                   f"({self.budget.used}/{self.budget.budget})")
                self.trail.append(cid, ev.STOPPED, "policy", out.stop_reason, "STOPPED")
                break
            if is_contact and not self.respect_budget:
                self.budget.used += 1

            # ---- execute ----------------------------------------------------
            self._go(out, "APPROVED")
            self._go(out, "EXECUTING")
            self.trail.append(cid, ev.EXECUTING, "executor",
                              f"executing {action}", "EXECUTING")

            result = self.executor.execute(case, action)
            out.attempts += 1
            out.attempted = True
            out.action_sequence.append(action)
            out.request_ids.append(result.request_id)
            if is_contact:
                out.contacts += 1
            self._charge(out, action)

            self._go(out, "WAITING")
            elapsed_h += self.engine.min_retry_interval_minutes / 60.0
            self.trail.append(cid, ev.WAITING, "executor",
                              f"request {result.request_id} in "
                              f"{result.latency_ms:.2f}ms; waiting "
                              f"{self.engine.min_retry_interval_minutes}m",
                              "WAITING", {"mode": result.mode,
                                          "detail": result.detail})

            self._go(out, "OUTCOME_CHECK")
            self.trail.append(cid, ev.OUTCOME_CHECK, "verifier",
                              "success" if result.success else "no recovery yet",
                              "OUTCOME_CHECK")

            if result.success:
                out.payment_success = True
                self._go(out, "RECOVERED")
                break

            # ---- stopping rules ---------------------------------------------
            if out.attempts >= self.engine.max_retry_attempts:
                # SEQUENTIAL ESCALATION -- the standby contact, reconsidered now
                # that the free retries are gone.
                cand = plan.escalation_action
                if (cand and not escalation_used
                        and out.contacts < self.engine.max_contacts_per_case
                        and (not self.respect_budget or self.budget.remaining > 0)):
                    escalation_used = True
                    out.escalated_sequentially = True
                    # Attempts reset for the escalation leg: the retry cap
                    # bounds retries, and the contact cap bounds contacts.
                    out.attempts = 0
                    action = cand
                    self.trail.append(
                        cid, ev.PLANNED, "allocator",
                        f"retries exhausted; escalating to standby {cand} "
                        f"(EV {plan.escalation_ev:.2f})", "OUTCOME_CHECK",
                        {"escalation": cand})
                    self._go(out, "RETRYABLE")
                    continue

                self._go(out, "STOPPED")
                out.stop_reason = (f"maximum attempts reached "
                                   f"({self.engine.max_retry_attempts})")
                self.trail.append(cid, ev.STOPPED, "executor", out.stop_reason,
                                  "STOPPED")
                break

            if is_contact and out.contacts >= self.engine.max_contacts_per_case:
                self._go(out, "STOPPED")
                out.stop_reason = (f"per-case contact limit reached "
                                   f"({self.engine.max_contacts_per_case})")
                self.trail.append(cid, ev.STOPPED, "policy", out.stop_reason, "STOPPED")
                break

            if case.get("age_hours", 0.0) + elapsed_h > OBSERVATION_WINDOW_HOURS:
                self._go(out, "STOPPED")
                out.stop_reason = "case aged out of the observation window"
                self.trail.append(cid, ev.STOPPED, "policy", out.stop_reason, "STOPPED")
                break

            self._go(out, "RETRYABLE")

        out.hours_elapsed = elapsed_h
        self._settle(case, out)
        return out

    # ---------------------------------------------------------------- settle

    def _skip_reason(self, plan: Plan) -> str:
        """Why a case was deliberately not pursued. Computed, never a label."""
        if plan.budget_rank is not None and not plan.won_contact:
            return (f"no positive-EV free action; best contact ranked "
                    f"{plan.budget_rank} of {plan.budget_contenders}, "
                    f"outside the budget")
        return (f"no action cleared its EV floor; best incremental EV "
                f"{plan.incremental_ev:.2f}")

    def _settle(self, case: dict[str, Any], out: CaseOutcome) -> None:
        """L6 -- separate verification. Executing is not evidence it worked.

        Two ideas are kept apart here, and keeping them apart is what makes the
        arm comparison honest:

          ``state``      what the WORKFLOW did -- recovered during our sequence,
                         stopped, escalated, or was never eligible.
          ``confirmed``  whether the MONEY came back inside the window, which
                         happens on plenty of cases the agent deliberately left
                         alone. That revenue belongs to the arm regardless.

        A case the agent skipped and which recovered anyway stays INELIGIBLE and
        still counts its revenue. Anything else would charge the agent for its
        own restraint, and would make the control arm incomparable.
        """
        if not out.attempted and out.state != "RECOVERED":
            # Nothing was executed. Observe the counterfactual.
            nat = self.executor.observe_no_action(case)
            out.payment_success = nat.success

        total_h = float(case.get("age_hours", 0.0)) + out.hours_elapsed
        v = verify(case, out.attempted, out.payment_success, total_h,
                   reversed_flag=self._is_reversed(out.case_id))

        out.confirmed = v.confirmed
        out.amount_confirmed = v.amount_confirmed

        if out.state == "RECOVERED" and not v.confirmed:
            # Apparent success that could not be confirmed is not a recovery.
            # This is L6 overruling the workflow, not a workflow transition, so
            # it deliberately bypasses the transition table rather than adding a
            # RECOVERED -> STOPPED edge that execution could otherwise take.
            out.state = "STOPPED"
            out.stop_reason = v.reason
            self.trail.append(out.case_id, ev.STOPPED, "verifier", v.reason, "STOPPED")
        elif v.confirmed:
            self.trail.append(
                out.case_id, ev.RECOVERED, "verifier",
                f"confirmed recovery of {v.amount_confirmed:.2f} within window"
                + ("" if out.attempted else " with no action taken"),
                out.state, {"amount": v.amount_confirmed,
                            "acted": out.attempted})

    @staticmethod
    def _is_reversed(case_id: str) -> bool:
        """A small share of apparent successes are later reversed. Derived from
        the case id so it is reproducible without threading an RNG through."""
        from agent.verification import REVERSAL_RATE
        h = 0
        for ch in case_id:
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
        return (h % 10000) / 10000.0 < REVERSAL_RATE
