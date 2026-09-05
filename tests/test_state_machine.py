"""L5 state machine tests -- boundedness, stopping, and sequential escalation."""

from __future__ import annotations

import pytest

from agent.audit import AuditTrail
from agent.diagnosis import Diagnosis
from agent.executors.simulator import ExecutionResult
from agent.policy import PolicyEngine
from agent.state_machine import (TERMINAL, TRANSITIONS, BudgetTracker,
                                 CaseOutcome, IllegalTransition, StateMachine)
from agent.valuation import Plan


class FakeExecutor:
    """Deterministic executor: succeeds on the Nth call, never before."""
    mode = "simulated"

    def __init__(self, succeed_on: int | None = None, natural: bool = False):
        self.succeed_on = succeed_on
        self.natural = natural
        self.calls: list[str] = []

    def execute(self, case, action):
        self.calls.append(action)
        ok = self.succeed_on is not None and len(self.calls) == self.succeed_on
        return ExecutionResult(ok, f"fake_{len(self.calls)}", 1.0, self.mode)

    def observe_no_action(self, case):
        return ExecutionResult(self.natural, "none", 0.0, self.mode)


@pytest.fixture
def eng():
    return PolicyEngine()


def mkcase(**over):
    base = {"case_id": "REC-1", "amount": 3000.0, "risk_score": 0.1,
            "opted_out": False, "disputed": False, "age_hours": 2.0, "hour": 14,
            "prior_failures": 0, "prior_success": 2, "tenure_days": 200}
    base.update(over)
    return base


def mkplan(**over):
    base = {"case_id": "REC-1", "action": "retry_immediate", "incremental_ev": 50.0,
            "uplift": 0.05, "p_natural": 0.3, "p_treated": 0.35}
    base.update(over)
    return Plan(**base)


def mkdiag():
    return Diagnosis("temporary_failure", 0.93, ["gateway code bank_technical_error"], "rules")


def run(eng, executor, plan, case=None, budget=100, respect=True, annoy=40.0):
    trail = AuditTrail()
    sm = StateMachine(eng, executor, trail, BudgetTracker(budget), annoy, respect)
    out = sm.run_case(case or mkcase(), mkdiag(), plan, "agent")
    return out, trail


# ===========================================================================
# Transition table
# ===========================================================================

def test_every_state_has_a_transition_entry():
    for state, targets in TRANSITIONS.items():
        for t in targets:
            assert t in TRANSITIONS, f"{state} -> {t} targets an unknown state"


def test_terminal_states_have_no_outgoing_transitions():
    for s in TERMINAL:
        assert TRANSITIONS[s] == frozenset()


def test_illegal_transition_raises(eng):
    sm = StateMachine(eng, FakeExecutor(), AuditTrail(), BudgetTracker(10), 40.0)
    out = CaseOutcome(case_id="X", arm="agent", state="FAILED")
    with pytest.raises(IllegalTransition):
        sm._go(out, "RECOVERED")


def test_agent_cannot_skip_from_scored_to_executing(eng):
    sm = StateMachine(eng, FakeExecutor(), AuditTrail(), BudgetTracker(10), 40.0)
    out = CaseOutcome(case_id="X", arm="agent", state="SCORED")
    with pytest.raises(IllegalTransition):
        sm._go(out, "EXECUTING")


# ===========================================================================
# Bounded retries
# ===========================================================================

def test_retries_are_bounded_by_the_policy_cap(eng):
    """Never more attempts than the cap, no matter how long it fails."""
    ex = FakeExecutor(succeed_on=None)
    plan = mkplan(escalation_action=None)
    out, _ = run(eng, ex, plan)
    assert out.attempts <= eng.max_retry_attempts
    assert ex.calls.count("retry_immediate") == eng.max_retry_attempts
    assert out.state == "STOPPED"
    assert "maximum attempts" in out.stop_reason


def test_recovers_and_stops_immediately_on_success(eng):
    out, _ = run(eng, FakeExecutor(succeed_on=1), mkplan(escalation_action=None))
    assert out.state == "RECOVERED"
    assert out.attempts == 1
    assert out.confirmed is True
    assert out.amount_confirmed == 3000.0


def test_no_further_attempts_after_recovery(eng):
    ex = FakeExecutor(succeed_on=2)
    out, _ = run(eng, ex, mkplan(escalation_action=None))
    assert out.attempts == 2 and len(ex.calls) == 2


# ===========================================================================
# Sequential escalation -- the trap in spec 13.2
# ===========================================================================

def test_escalates_to_standby_contact_after_retries_are_exhausted(eng):
    """Without this the agent does structurally less work than a naive bot that
    retries three times AND THEN messages."""
    ex = FakeExecutor(succeed_on=None)
    plan = mkplan(escalation_action="sms_payment_link", escalation_ev=90.0)
    out, _ = run(eng, ex, plan)
    assert out.escalated_sequentially is True
    assert "sms_payment_link" in ex.calls
    assert ex.calls.count("retry_immediate") == eng.max_retry_attempts


def test_escalation_can_recover_the_case(eng):
    ex = FakeExecutor(succeed_on=4)   # 3 retries fail, the contact lands
    plan = mkplan(escalation_action="sms_payment_link", escalation_ev=90.0)
    out, _ = run(eng, ex, plan)
    assert out.state == "RECOVERED"
    assert out.contacts == 1
    assert out.escalated_sequentially is True


def test_escalation_happens_only_once(eng):
    ex = FakeExecutor(succeed_on=None)
    plan = mkplan(escalation_action="sms_payment_link")
    out, _ = run(eng, ex, plan)
    assert ex.calls.count("sms_payment_link") <= eng.max_contacts_per_case


def test_no_escalation_when_no_standby_candidate(eng):
    ex = FakeExecutor(succeed_on=None)
    out, _ = run(eng, ex, mkplan(escalation_action=None))
    assert out.escalated_sequentially is False
    assert out.contacts == 0


def test_escalation_blocked_when_batch_budget_is_exhausted(eng):
    ex = FakeExecutor(succeed_on=None)
    plan = mkplan(escalation_action="sms_payment_link")
    out, _ = run(eng, ex, plan, budget=0)
    assert out.escalated_sequentially is False
    assert "sms_payment_link" not in ex.calls


def test_escalation_respects_opt_out(eng):
    ex = FakeExecutor(succeed_on=None)
    plan = mkplan(escalation_action="sms_payment_link")
    out, _ = run(eng, ex, plan, case=mkcase(opted_out=True))
    assert "sms_payment_link" not in ex.calls
    assert out.stop_reason.startswith("policy R3")


# ===========================================================================
# Stopping rules
# ===========================================================================

def test_disputed_case_stops_before_any_execution(eng):
    ex = FakeExecutor(succeed_on=1)
    out, _ = run(eng, ex, mkplan(), case=mkcase(disputed=True))
    assert out.state == "STOPPED"
    assert ex.calls == []
    assert "R1" in out.stop_reason


def test_high_risk_case_stops_before_any_execution(eng):
    ex = FakeExecutor(succeed_on=1)
    out, _ = run(eng, ex, mkplan(), case=mkcase(risk_score=0.95))
    assert out.state == "STOPPED" and ex.calls == []
    assert "R2" in out.stop_reason


def test_aged_out_case_stops(eng):
    ex = FakeExecutor(succeed_on=1)
    out, _ = run(eng, ex, mkplan(), case=mkcase(age_hours=200.0))
    assert out.state == "STOPPED" and "R7" in out.stop_reason


def test_high_value_case_escalates_and_does_not_execute(eng):
    ex = FakeExecutor(succeed_on=1)
    out, _ = run(eng, ex, mkplan(), case=mkcase(amount=60000.0))
    assert out.state == "ESCALATED"
    assert ex.calls == []


def test_no_action_plan_is_ineligible_and_executes_nothing(eng):
    ex = FakeExecutor(succeed_on=1)
    out, _ = run(eng, ex, mkplan(action="no_action", incremental_ev=-12.0))
    assert out.state == "INELIGIBLE"
    assert ex.calls == []
    assert out.cost_spent == 0.0


def test_every_run_reaches_a_terminal_state(eng):
    for case in [mkcase(), mkcase(disputed=True), mkcase(risk_score=0.99),
                 mkcase(amount=90000.0), mkcase(opted_out=True),
                 mkcase(age_hours=500.0)]:
        out, _ = run(eng, FakeExecutor(succeed_on=None),
                     mkplan(escalation_action="sms_payment_link"), case=case)
        assert out.state in TERMINAL


def test_stop_reason_is_always_populated_when_stopped(eng):
    out, _ = run(eng, FakeExecutor(succeed_on=None), mkplan(escalation_action=None))
    assert out.state == "STOPPED" and out.stop_reason


# ===========================================================================
# Natural recovery on cases the agent left alone
# ===========================================================================

def test_skipped_case_that_recovers_naturally_still_counts_its_revenue(eng):
    """Charging the agent for its own restraint would make the arms
    incomparable."""
    ex = FakeExecutor(succeed_on=None, natural=True)
    out, _ = run(eng, ex, mkplan(action="no_action"))
    assert out.state == "INELIGIBLE"
    assert out.confirmed is True
    assert out.amount_confirmed == 3000.0
    assert out.cost_spent == 0.0


def test_skipped_case_that_does_not_recover_counts_nothing(eng):
    ex = FakeExecutor(succeed_on=None, natural=False)
    out, _ = run(eng, ex, mkplan(action="no_action"))
    assert out.confirmed is False and out.amount_confirmed == 0.0


def test_blocked_case_still_observes_natural_recovery(eng):
    ex = FakeExecutor(succeed_on=None, natural=True)
    out, _ = run(eng, ex, mkplan(), case=mkcase(disputed=True))
    assert out.state == "STOPPED" and out.confirmed is True


# ===========================================================================
# Quiet hours deferral
# ===========================================================================

def test_contact_in_quiet_hours_is_deferred_not_dropped(eng):
    ex = FakeExecutor(succeed_on=1)
    plan = mkplan(action="sms_payment_link", incremental_ev=200.0)
    out, _ = run(eng, ex, plan, case=mkcase(hour=23))
    assert out.deferrals >= 1
    assert "sms_payment_link" in ex.calls, "the contact must still be sent"
    assert out.state == "RECOVERED"


def test_retry_in_quiet_hours_is_not_deferred(eng):
    ex = FakeExecutor(succeed_on=1)
    out, _ = run(eng, ex, mkplan(), case=mkcase(hour=2))
    assert out.deferrals == 0


# ===========================================================================
# Cost accounting
# ===========================================================================

def test_contact_is_charged_annoyance_cost_on_top_of_send_cost(eng):
    ex = FakeExecutor(succeed_on=1)
    plan = mkplan(action="sms_payment_link", incremental_ev=300.0)
    out, _ = run(eng, ex, plan, annoy=40.0)
    assert out.cost_spent == pytest.approx(40.25)


def test_retry_is_not_charged_annoyance_cost(eng):
    out, _ = run(eng, FakeExecutor(succeed_on=1), mkplan(escalation_action=None))
    assert out.cost_spent == pytest.approx(2.00)


def test_cost_accumulates_across_the_sequence(eng):
    out, _ = run(eng, FakeExecutor(succeed_on=None), mkplan(escalation_action=None))
    assert out.cost_spent == pytest.approx(6.00)   # three retries


# ===========================================================================
# Budget
# ===========================================================================

def test_budget_tracker_refuses_to_overspend():
    b = BudgetTracker(2)
    assert b.take() and b.take()
    assert not b.take()
    assert b.used == 2 and b.remaining == 0


def test_naive_mode_ignores_the_budget_but_still_counts_contacts(eng):
    ex = FakeExecutor(succeed_on=None)
    plan = mkplan(action="sms_payment_link", incremental_ev=200.0)
    out, _ = run(eng, ex, plan, budget=0, respect=False)
    assert out.contacts >= 1, "the naive arm is not budget-constrained"


# ===========================================================================
# Audit trail
# ===========================================================================

def test_audit_trail_records_the_whole_sequence(eng):
    out, trail = run(eng, FakeExecutor(succeed_on=None),
                     mkplan(escalation_action="sms_payment_link"))
    events = [e.event for e in trail.events("REC-1")]
    for expected in ["DIAGNOSED", "SCORED", "PLANNED", "POLICY_CHECKED",
                     "EXECUTING", "WAITING", "OUTCOME_CHECK", "STOPPED"]:
        assert expected in events


def test_audit_timestamps_have_millisecond_precision(eng):
    _, trail = run(eng, FakeExecutor(succeed_on=1), mkplan())
    for e in trail.events("REC-1"):
        assert "." in e.timestamp
        assert len(e.timestamp.split(".")[-1]) == 3


def test_policy_events_carry_the_full_rule_trace(eng):
    _, trail = run(eng, FakeExecutor(succeed_on=1), mkplan())
    pol = [e for e in trail.events("REC-1") if e.event == "POLICY_CHECKED"]
    assert pol and len(pol[0].payload["rules"]) == 8


def test_audit_trail_is_append_only():
    trail = AuditTrail()
    trail.append("A", "DIAGNOSED", "rules", "x", "DIAGNOSED")
    trail.append("A", "SCORED", "rules", "y", "SCORED")
    assert len(trail.events("A")) == 2
    assert not any(m.startswith(("remove", "delete", "update", "pop", "clear"))
                   for m in dir(trail))


# ===========================================================================
# Skip reasons must name the cause that actually applied
# ===========================================================================

def _plan_with_alternatives(blocked_rules, evs, budget_rank=None):
    from agent.valuation import Alternative
    alts = [Alternative(action="no_action", uplift=0.0, p_natural=0.3,
                        p_treated=0.3, cost=0.0, consumes_contact=False,
                        incremental_ev=0.0, selected=True)]
    for action, ev in evs.items():
        rule_id = blocked_rules.get(action)
        alts.append(Alternative(
            action=action, uplift=0.05, p_natural=0.3, p_treated=0.35,
            cost=2.0, consumes_contact=action.startswith(("sms", "whatsapp",
                                                          "method", "human")),
            incremental_ev=ev,
            rejection_type="policy" if rule_id else "ev_floor",
            rejection_detail=f"blocked by {rule_id}" if rule_id else "below floor",
            blocked_by=rule_id))
    return Plan(case_id="REC-1", action="no_action", alternatives=alts,
                budget_rank=budget_rank, budget_contenders=90)


def test_skip_reason_names_the_rule_when_every_action_is_blocked(eng):
    """A large payment the policy engine timed out is not a payment that
    'failed to clear its EV floor'. Reporting it that way hides a stopping rule
    firing on real money."""
    sm = StateMachine(eng, FakeExecutor(), AuditTrail(), BudgetTracker(10), 40.0)
    plan = _plan_with_alternatives(
        {a: "R7" for a in ("retry_immediate", "method_update_request")},
        {"retry_immediate": -1535.24, "method_update_request": 4180.06})
    reason = sm._skip_reason(plan)
    assert "R7" in reason
    assert "every action refused by policy" in reason
    assert "4180.06" in reason, "must surface the EV it deliberately forwent"


def test_skip_reason_falls_back_to_ev_floor_when_nothing_is_blocked(eng):
    sm = StateMachine(eng, FakeExecutor(), AuditTrail(), BudgetTracker(10), 40.0)
    plan = _plan_with_alternatives({}, {"retry_immediate": 0.2})
    reason = sm._skip_reason(plan)
    assert "EV floor" in reason and "R" not in reason.replace("REC", "")


def test_skip_reason_reports_partial_blocking_distinctly(eng):
    sm = StateMachine(eng, FakeExecutor(), AuditTrail(), BudgetTracker(10), 40.0)
    plan = _plan_with_alternatives(
        {"sms_payment_link": "R3"},
        {"retry_immediate": 0.1, "sms_payment_link": 900.0})
    reason = sm._skip_reason(plan)
    assert "R3" in reason and "refused" in reason
