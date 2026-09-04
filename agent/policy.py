"""L4 -- Policy engine.

Three properties, all load-bearing:

  1. FULLY DETERMINISTIC.  No LLM is consulted at any point.  Given the same
     case, action and context, this returns the same decision forever.

  2. TOTAL EVALUATION.  Every rule runs on every case and its result is
     recorded even when it passes.  This is what makes "8 rules evaluated,
     0 violations across 1,000 cases" a measurement rather than a badge --
     the passes are counted, not assumed.

  3. OUTSIDE THE LLM BOUNDARY.  Nothing upstream can talk its way past a rule.
     An action arrives here as a proposal; it leaves as ALLOW, ESCALATE or
     BLOCK, and no other component may overrule that.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from agent.constants import CONTACT_ACTIONS

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POLICY_PATH = os.path.join(HERE, "policy.yaml")

ALLOW = "ALLOW"
ESCALATE = "ESCALATE"
BLOCK = "BLOCK"


@dataclass
class RuleResult:
    """One rule, on one case.  Recorded whether it passed or failed."""
    rule_id: str
    name: str
    applies: bool          # did this rule have jurisdiction over this action?
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "applies": self.applies,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class PolicyDecision:
    outcome: str                       # ALLOW | ESCALATE | BLOCK
    action: str
    rules: list[RuleResult] = field(default_factory=list)
    blocked_by: str | None = None      # rule id
    block_detail: str = ""
    deferred: bool = False
    deferred_to_hour: int | None = None
    escalation_reason: str = ""

    @property
    def rules_evaluated(self) -> int:
        return len(self.rules)

    @property
    def rules_applicable(self) -> int:
        return sum(1 for r in self.rules if r.applies)

    @property
    def violations(self) -> list[RuleResult]:
        return [r for r in self.rules if r.applies and not r.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "action": self.action,
            "rules": [r.to_dict() for r in self.rules],
            "rules_evaluated": self.rules_evaluated,
            "rules_applicable": self.rules_applicable,
            "violations": [r.rule_id for r in self.violations],
            "blocked_by": self.blocked_by,
            "block_detail": self.block_detail,
            "deferred": self.deferred,
            "deferred_to_hour": self.deferred_to_hour,
            "escalation_reason": self.escalation_reason,
        }


@dataclass
class PolicyContext:
    """Everything the engine needs that is not on the case record itself."""
    attempts_used: int = 0
    contacts_used_case: int = 0
    contacts_used_batch: int = 0
    intended_hour: int | None = None    # IST hour the action would land at
    incremental_ev: float | None = None
    minutes_since_last_attempt: float = 1e9


class PolicyEngine:
    def __init__(self, path: str = DEFAULT_POLICY_PATH) -> None:
        with open(path) as fh:
            cfg = yaml.safe_load(fh)
        self.cfg = cfg
        self.path = path

        lim = cfg["limits"]
        self.max_retry_attempts: int = lim["max_retry_attempts"]
        self.min_retry_interval_minutes: int = lim["min_retry_interval_minutes"]
        self.max_contacts_per_case: int = lim["max_contacts_per_case"]
        self.contact_budget_per_batch: int = lim["contact_budget_per_batch"]
        self.max_case_age_hours: float = float(lim["max_case_age_hours"])

        qh = cfg["quiet_hours"]
        self.quiet_start: int = qh["start_hour"]
        self.quiet_end: int = qh["end_hour"]

        th = cfg["thresholds"]
        self.high_value_inr: float = float(th["high_value_inr"])
        self.risk_block: float = float(th["risk_block"])

        ev = cfg["ev_floors"]
        self.ev_floor_contact: float = float(ev["contact_actions_inr"])
        self.ev_floor_zero_contact: float = float(ev["zero_contact_actions_inr"])

        self.permitted_actions: list[str] = list(cfg["permitted_actions"])

    # ---------------------------------------------------------------- helpers

    def is_quiet_hour(self, hour: int) -> bool:
        """Quiet window wraps midnight, so this is an OR, not a range test."""
        if self.quiet_start > self.quiet_end:
            return hour >= self.quiet_start or hour < self.quiet_end
        return self.quiet_start <= hour < self.quiet_end

    def ev_floor_for(self, action: str) -> float:
        return (self.ev_floor_contact if action in CONTACT_ACTIONS
                else self.ev_floor_zero_contact)

    # ---------------------------------------------------------------- evaluate

    def evaluate(self, case: dict[str, Any], action: str,
                 ctx: PolicyContext | None = None) -> PolicyDecision:
        """Evaluate ALL eight rules against one proposed action.

        Rules are evaluated in full even after one has already failed, so that
        the trace shows every rule's verdict rather than stopping at the first
        problem. The outcome is decided afterwards from the collected results.
        """
        ctx = ctx or PolicyContext()
        is_contact = action in CONTACT_ACTIONS
        rules: list[RuleResult] = []

        # ---- R8: permitted enumeration ------------------------------------
        # First, because if the action is not a real action the remaining rules
        # are meaningless. Still evaluated alongside the others, not short-circuited.
        r8_ok = action in self.permitted_actions
        rules.append(RuleResult(
            "R8", "Action is in the permitted enumeration", True, r8_ok,
            f"{action!r} permitted" if r8_ok
            else f"{action!r} is not a permitted action"))

        # `no_action` needs no permission: doing nothing is always allowed.
        # It is still run through R8 above so an invalid string cannot sneak
        # through by claiming to be inaction.
        if action == "no_action" and r8_ok:
            return PolicyDecision(outcome=ALLOW, action=action, rules=rules)

        # ---- R1: dispute ---------------------------------------------------
        disputed = bool(case.get("disputed", False))
        rules.append(RuleResult(
            "R1", "Case is not disputed", True, not disputed,
            "no dispute on file" if not disputed
            else "case is under dispute; no recovery action permitted"))

        # ---- R2: risk ------------------------------------------------------
        risk = float(case.get("risk_score", 0.0))
        r2_ok = risk < self.risk_block
        rules.append(RuleResult(
            "R2", "Risk score below block threshold", True, r2_ok,
            f"risk {risk:.3f} < {self.risk_block}" if r2_ok
            else f"risk {risk:.3f} >= {self.risk_block}"))

        # ---- R3: opt-out (contact actions only) ----------------------------
        opted_out = bool(case.get("opted_out", False))
        r3_ok = not (is_contact and opted_out)
        rules.append(RuleResult(
            "R3", "Customer has not opted out of contact", is_contact, r3_ok,
            ("customer has opted out of communication" if not r3_ok
             else ("opt-out clear" if is_contact else "not a contact action"))))

        # ---- R4: retry cap -------------------------------------------------
        r4_ok = ctx.attempts_used < self.max_retry_attempts
        rules.append(RuleResult(
            "R4", "Attempts below cap", True, r4_ok,
            f"{ctx.attempts_used} of {self.max_retry_attempts} attempts used"))

        # ---- R5: per-case contact cap (contact actions only) ---------------
        r5_ok = not (is_contact and ctx.contacts_used_case >= self.max_contacts_per_case)
        rules.append(RuleResult(
            "R5", "Per-case contact count below cap", is_contact, r5_ok,
            (f"{ctx.contacts_used_case} of {self.max_contacts_per_case} contacts used"
             if is_contact else "not a contact action")))

        # ---- R6: quiet hours -> DEFER, never cancel ------------------------
        hour = ctx.intended_hour if ctx.intended_hour is not None else int(case.get("hour", 12))
        in_quiet = is_contact and self.is_quiet_hour(hour)
        # R6 never fails. Landing in quiet hours is not a violation; it is a
        # scheduling fact. Recording it as a pass with a deferral is the whole
        # point -- a blocked contact is discarded revenue for no compliance gain.
        rules.append(RuleResult(
            "R6", "Quiet hours respected", is_contact, True,
            (f"{hour:02d}:00 IST is inside quiet hours "
             f"{self.quiet_start:02d}:00-{self.quiet_end:02d}:00; "
             f"deferred to {self.quiet_end:02d}:00" if in_quiet
             else (f"{hour:02d}:00 IST is outside quiet hours" if is_contact
                   else "not a contact action"))))

        # ---- R7: case age --------------------------------------------------
        age = float(case.get("age_hours", 0.0))
        r7_ok = age <= self.max_case_age_hours
        rules.append(RuleResult(
            "R7", "Case age within limit", True, r7_ok,
            f"{age:.1f}h of {self.max_case_age_hours:.0f}h" if r7_ok
            else f"{age:.1f}h exceeds {self.max_case_age_hours:.0f}h limit"))

        # ---- outcome -------------------------------------------------------
        decision = PolicyDecision(outcome=ALLOW, action=action, rules=rules)

        failed = [r for r in rules if r.applies and not r.passed]
        if failed:
            first = failed[0]
            decision.outcome = BLOCK
            decision.blocked_by = first.rule_id
            decision.block_detail = first.detail
            return decision

        if in_quiet:
            decision.deferred = True
            decision.deferred_to_hour = self.quiet_end

        # High value routes to a human. This is not a block; it is a routing
        # decision, and it is deliberately evaluated after the rules so that a
        # high-value case that also violates a rule reports the violation.
        if float(case.get("amount", 0.0)) >= self.high_value_inr:
            decision.outcome = ESCALATE
            decision.escalation_reason = (
                f"amount {case.get('amount'):.2f} >= high-value threshold "
                f"{self.high_value_inr:.0f}; requires human approval")

        return decision


_DEFAULT: PolicyEngine | None = None


def default_engine() -> PolicyEngine:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = PolicyEngine()
    return _DEFAULT
