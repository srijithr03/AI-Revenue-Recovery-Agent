"""L4 policy engine tests.

The policy engine is the component that stands between a language model and a
customer's money, so it is tested adversarially: every test here is written as
"what if something upstream proposes the wrong thing".
"""

from __future__ import annotations

import pytest

from agent.constants import CONTACT_ACTIONS
from agent.policy import ALLOW, BLOCK, ESCALATE, PolicyContext, PolicyEngine


@pytest.fixture(scope="module")
def eng() -> PolicyEngine:
    return PolicyEngine()


def mkcase(**over):
    base = {
        "case_id": "REC-TEST",
        "amount": 3000.0,
        "risk_score": 0.10,
        "opted_out": False,
        "disputed": False,
        "age_hours": 4.0,
        "hour": 14,
        "prior_failures": 0,
    }
    base.update(over)
    return base


# ===========================================================================
# Structural properties
# ===========================================================================

def test_config_loads_from_yaml(eng):
    assert eng.max_retry_attempts == 3
    assert eng.max_contacts_per_case == 2
    assert eng.contact_budget_per_batch == 150
    assert eng.risk_block == 0.7
    assert eng.high_value_inr == 25000.0


def test_two_distinct_ev_floors_exist(eng):
    """The single-floor trap: one threshold for retries and contacts suppresses
    hundreds of profitable retries. They must differ, and by a lot."""
    assert eng.ev_floor_contact > eng.ev_floor_zero_contact
    assert eng.ev_floor_contact >= 50.0
    assert eng.ev_floor_zero_contact <= 1.0


def test_ev_floor_selected_by_action_type(eng):
    assert eng.ev_floor_for("sms_payment_link") == eng.ev_floor_contact
    assert eng.ev_floor_for("whatsapp_nudge") == eng.ev_floor_contact
    assert eng.ev_floor_for("human_escalation") == eng.ev_floor_contact
    assert eng.ev_floor_for("retry_immediate") == eng.ev_floor_zero_contact
    assert eng.ev_floor_for("retry_delayed") == eng.ev_floor_zero_contact


def test_evaluation_is_total_all_eight_rules_recorded(eng):
    """Every rule runs on every case, even when it passes and even when an
    earlier rule already failed."""
    d = eng.evaluate(mkcase(), "retry_immediate")
    ids = [r.rule_id for r in d.rules]
    assert sorted(ids) == ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    assert d.rules_evaluated == 8


def test_all_rules_still_recorded_when_one_fails(eng):
    d = eng.evaluate(mkcase(disputed=True), "sms_payment_link")
    assert d.outcome == BLOCK
    assert d.rules_evaluated == 8, "must not short-circuit the trace"


def test_passing_rules_are_recorded_not_just_failures(eng):
    d = eng.evaluate(mkcase(), "retry_immediate")
    passed = [r for r in d.rules if r.passed]
    assert len(passed) == 8
    assert all(r.detail for r in d.rules), "every rule records a reason"


def test_engine_is_deterministic(eng):
    c = mkcase()
    a = eng.evaluate(c, "sms_payment_link", PolicyContext(intended_hour=14))
    b = eng.evaluate(c, "sms_payment_link", PolicyContext(intended_hour=14))
    assert a.to_dict() == b.to_dict()


# ===========================================================================
# R1 -- disputes
# ===========================================================================

def test_r1_blocks_disputed_case_for_retry(eng):
    d = eng.evaluate(mkcase(disputed=True), "retry_immediate")
    assert d.outcome == BLOCK and d.blocked_by == "R1"


def test_r1_blocks_disputed_case_for_contact(eng):
    d = eng.evaluate(mkcase(disputed=True), "whatsapp_nudge")
    assert d.outcome == BLOCK and d.blocked_by == "R1"


def test_r1_blocks_disputed_even_when_high_value(eng):
    """A dispute outranks the escalation route -- it must not become ESCALATE."""
    d = eng.evaluate(mkcase(disputed=True, amount=90000.0), "human_escalation")
    assert d.outcome == BLOCK and d.blocked_by == "R1"


def test_r1_passes_when_not_disputed(eng):
    d = eng.evaluate(mkcase(disputed=False), "retry_immediate")
    r1 = next(r for r in d.rules if r.rule_id == "R1")
    assert r1.passed and r1.applies


# ===========================================================================
# R2 -- risk
# ===========================================================================

def test_r2_blocks_above_risk_threshold(eng):
    d = eng.evaluate(mkcase(risk_score=0.85), "retry_immediate")
    assert d.outcome == BLOCK and d.blocked_by == "R2"


def test_r2_blocks_exactly_at_threshold_boundary(eng):
    """0.7 is blocked: the rule is 'below threshold', not 'at or below'."""
    d = eng.evaluate(mkcase(risk_score=0.7), "retry_immediate")
    assert d.outcome == BLOCK and d.blocked_by == "R2"


def test_r2_allows_just_below_threshold_boundary(eng):
    d = eng.evaluate(mkcase(risk_score=0.699), "retry_immediate")
    assert d.outcome == ALLOW


def test_r2_applies_to_contact_actions_too(eng):
    d = eng.evaluate(mkcase(risk_score=0.9), "sms_payment_link")
    assert d.outcome == BLOCK and d.blocked_by == "R2"


def test_r2_blocks_human_escalation_on_high_risk(eng):
    """Deliberate conservative choice: a high-risk case is blocked outright and
    surfaced, rather than routed anywhere automatically."""
    d = eng.evaluate(mkcase(risk_score=0.95, amount=50000.0), "human_escalation")
    assert d.outcome == BLOCK and d.blocked_by == "R2"


# ===========================================================================
# R3 -- opt-out
# ===========================================================================

@pytest.mark.parametrize("action", sorted(CONTACT_ACTIONS))
def test_r3_blocks_every_contact_action_for_opted_out_customer(eng, action):
    d = eng.evaluate(mkcase(opted_out=True), action)
    assert d.outcome == BLOCK and d.blocked_by == "R3"


@pytest.mark.parametrize("action", ["retry_immediate", "retry_delayed"])
def test_r3_does_not_block_retries_for_opted_out_customer(eng, action):
    """Opting out of communication is not opting out of having the payment
    retried. Conflating them would discard recoverable revenue."""
    d = eng.evaluate(mkcase(opted_out=True), action)
    assert d.outcome == ALLOW


def test_r3_marked_not_applicable_for_retries(eng):
    d = eng.evaluate(mkcase(opted_out=True), "retry_immediate")
    r3 = next(r for r in d.rules if r.rule_id == "R3")
    assert r3.applies is False


# ===========================================================================
# R4 -- attempt cap
# ===========================================================================

def test_r4_blocks_fourth_attempt_when_cap_is_three(eng):
    """The adversarial case: something upstream proposes a fourth retry."""
    d = eng.evaluate(mkcase(), "retry_immediate", PolicyContext(attempts_used=3))
    assert d.outcome == BLOCK and d.blocked_by == "R4"


def test_r4_allows_third_attempt(eng):
    d = eng.evaluate(mkcase(), "retry_immediate", PolicyContext(attempts_used=2))
    assert d.outcome == ALLOW


def test_r4_blocks_far_beyond_cap(eng):
    d = eng.evaluate(mkcase(), "retry_delayed", PolicyContext(attempts_used=99))
    assert d.outcome == BLOCK and d.blocked_by == "R4"


def test_r4_applies_to_contact_actions_too(eng):
    d = eng.evaluate(mkcase(), "sms_payment_link", PolicyContext(attempts_used=3))
    assert d.outcome == BLOCK and d.blocked_by == "R4"


# ===========================================================================
# R5 -- per-case contact cap
# ===========================================================================

def test_r5_blocks_third_contact_when_cap_is_two(eng):
    d = eng.evaluate(mkcase(), "sms_payment_link",
                     PolicyContext(contacts_used_case=2, intended_hour=14))
    assert d.outcome == BLOCK and d.blocked_by == "R5"


def test_r5_allows_second_contact(eng):
    d = eng.evaluate(mkcase(), "sms_payment_link",
                     PolicyContext(contacts_used_case=1, intended_hour=14))
    assert d.outcome == ALLOW


def test_r5_does_not_restrict_retries(eng):
    d = eng.evaluate(mkcase(), "retry_immediate",
                     PolicyContext(contacts_used_case=9))
    assert d.outcome == ALLOW


# ===========================================================================
# R6 -- quiet hours DEFER, never cancel
# ===========================================================================

def test_r6_defers_contact_inside_quiet_hours_rather_than_blocking(eng):
    """The trap: blocking here silently kills roughly a third of the contact
    plan for no compliance benefit."""
    d = eng.evaluate(mkcase(), "sms_payment_link", PolicyContext(intended_hour=23))
    assert d.outcome == ALLOW
    assert d.deferred is True
    assert d.deferred_to_hour == 9


def test_r6_defers_at_quiet_window_start(eng):
    d = eng.evaluate(mkcase(), "whatsapp_nudge", PolicyContext(intended_hour=21))
    assert d.deferred is True


def test_r6_defers_after_midnight(eng):
    """The window wraps midnight; 03:00 is inside it."""
    d = eng.evaluate(mkcase(), "sms_payment_link", PolicyContext(intended_hour=3))
    assert d.deferred is True and d.outcome == ALLOW


def test_r6_does_not_defer_at_quiet_window_end(eng):
    d = eng.evaluate(mkcase(), "sms_payment_link", PolicyContext(intended_hour=9))
    assert d.deferred is False


def test_r6_does_not_defer_at_midday(eng):
    d = eng.evaluate(mkcase(), "sms_payment_link", PolicyContext(intended_hour=12))
    assert d.deferred is False


def test_r6_never_defers_a_retry(eng):
    """Quiet hours protect the customer from being messaged, not the gateway
    from being called."""
    d = eng.evaluate(mkcase(), "retry_immediate", PolicyContext(intended_hour=2))
    assert d.deferred is False and d.outcome == ALLOW


def test_r6_records_a_pass_not_a_violation(eng):
    d = eng.evaluate(mkcase(), "sms_payment_link", PolicyContext(intended_hour=23))
    r6 = next(r for r in d.rules if r.rule_id == "R6")
    assert r6.passed is True
    assert d.violations == []


@pytest.mark.parametrize("hour,expected", [
    (0, True), (5, True), (8, True), (9, False), (12, False),
    (20, False), (21, True), (22, True), (23, True),
])
def test_quiet_hour_window_boundaries(eng, hour, expected):
    assert eng.is_quiet_hour(hour) is expected


# ===========================================================================
# R7 -- case age
# ===========================================================================

def test_r7_blocks_case_older_than_limit(eng):
    d = eng.evaluate(mkcase(age_hours=100.0), "retry_immediate")
    assert d.outcome == BLOCK and d.blocked_by == "R7"


def test_r7_allows_case_exactly_at_limit(eng):
    d = eng.evaluate(mkcase(age_hours=72.0), "retry_immediate")
    assert d.outcome == ALLOW


def test_r7_blocks_just_past_limit(eng):
    d = eng.evaluate(mkcase(age_hours=72.01), "retry_immediate")
    assert d.outcome == BLOCK and d.blocked_by == "R7"


# ===========================================================================
# R8 -- permitted enumeration.  The LLM boundary, enforced.
# ===========================================================================

def test_r8_blocks_action_outside_enumeration(eng):
    d = eng.evaluate(mkcase(), "call_customer_at_home")
    assert d.outcome == BLOCK and d.blocked_by == "R8"


def test_r8_blocks_plausible_looking_invented_action(eng):
    """The realistic failure: a model invents something that sounds reasonable."""
    d = eng.evaluate(mkcase(), "send_email_reminder")
    assert d.outcome == BLOCK and d.blocked_by == "R8"


def test_r8_blocks_empty_action(eng):
    assert eng.evaluate(mkcase(), "").outcome == BLOCK


def test_r8_blocks_case_variant_of_a_real_action(eng):
    assert eng.evaluate(mkcase(), "SMS_PAYMENT_LINK").outcome == BLOCK


def test_r8_blocks_injection_shaped_action_string(eng):
    d = eng.evaluate(mkcase(), "no_action; refund_customer(100000)")
    assert d.outcome == BLOCK and d.blocked_by == "R8"


def test_r8_blocks_fake_no_action(eng):
    """An invalid string must not get the free pass that real inaction gets."""
    d = eng.evaluate(mkcase(), "no_action_really")
    assert d.outcome == BLOCK and d.blocked_by == "R8"


@pytest.mark.parametrize("action", [
    "no_action", "retry_immediate", "retry_delayed", "sms_payment_link",
    "whatsapp_nudge", "method_update_request", "human_escalation",
])
def test_r8_admits_every_permitted_action(eng, action):
    d = eng.evaluate(mkcase(), action, PolicyContext(intended_hour=14))
    r8 = next(r for r in d.rules if r.rule_id == "R8")
    assert r8.passed


# ===========================================================================
# Escalation routing
# ===========================================================================

def test_high_value_case_escalates_rather_than_executing(eng):
    d = eng.evaluate(mkcase(amount=40000.0), "retry_immediate")
    assert d.outcome == ESCALATE
    assert "human approval" in d.escalation_reason


def test_high_value_boundary_escalates_at_threshold(eng):
    assert eng.evaluate(mkcase(amount=25000.0), "retry_immediate").outcome == ESCALATE


def test_just_below_high_value_threshold_executes(eng):
    assert eng.evaluate(mkcase(amount=24999.99), "retry_immediate").outcome == ALLOW


def test_escalation_is_not_a_block(eng):
    d = eng.evaluate(mkcase(amount=40000.0), "retry_immediate")
    assert d.blocked_by is None and d.violations == []


def test_rule_violation_outranks_escalation(eng):
    """A high-value case that breaks a rule must report the violation, not be
    quietly re-routed to a human as though nothing were wrong."""
    d = eng.evaluate(mkcase(amount=40000.0, age_hours=200.0), "retry_immediate")
    assert d.outcome == BLOCK and d.blocked_by == "R7"


# ===========================================================================
# no_action
# ===========================================================================

def test_no_action_is_always_allowed(eng):
    d = eng.evaluate(mkcase(disputed=True, opted_out=True, risk_score=0.99,
                            age_hours=500.0), "no_action")
    assert d.outcome == ALLOW


def test_no_action_on_high_value_does_not_escalate(eng):
    """Doing nothing needs no human approval."""
    assert eng.evaluate(mkcase(amount=90000.0), "no_action").outcome == ALLOW


# ===========================================================================
# Combined adversarial scenarios
# ===========================================================================

def test_opted_out_and_over_retry_cap_reports_first_violation(eng):
    d = eng.evaluate(mkcase(opted_out=True), "sms_payment_link",
                     PolicyContext(attempts_used=5))
    assert d.outcome == BLOCK
    assert len(d.violations) >= 2
    assert d.blocked_by == "R3"


def test_every_rule_failing_at_once_still_produces_full_trace(eng):
    d = eng.evaluate(
        mkcase(disputed=True, risk_score=0.99, opted_out=True, age_hours=999.0),
        "sms_payment_link",
        PolicyContext(attempts_used=9, contacts_used_case=9, intended_hour=23))
    assert d.outcome == BLOCK
    assert d.rules_evaluated == 8
    assert {r.rule_id for r in d.violations} == {"R1", "R2", "R3", "R4", "R5", "R7"}


def test_quiet_hours_deferral_survives_an_otherwise_clean_high_value_case(eng):
    d = eng.evaluate(mkcase(amount=60000.0), "whatsapp_nudge",
                     PolicyContext(intended_hour=23))
    assert d.outcome == ESCALATE
    assert d.deferred is True
