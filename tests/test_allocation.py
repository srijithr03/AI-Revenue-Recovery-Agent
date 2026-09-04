"""L3 allocation tests.

The property under test throughout: allocation ranks contacts by their MARGINAL
gain over the free action a case is already getting, not by the absolute value
of the case. A large payment whose contact adds little must lose to a small
payment whose contact adds a lot.
"""

from __future__ import annotations

import pytest

from agent.constants import ACTIONS, CONTACT_ACTIONS
from agent.policy import PolicyEngine
from agent.uplift import ActionScore, CaseScore
from agent.valuation import (DEFAULT_ANNOYANCE_COST, Allocator, action_cost)


@pytest.fixture(scope="module")
def eng():
    return PolicyEngine()


def mkcase(cid="REC-1", amount=3000.0, **over):
    base = {"case_id": cid, "amount": amount, "risk_score": 0.1,
            "opted_out": False, "disputed": False, "age_hours": 2.0, "hour": 14,
            "prior_failures": 0, "prior_success": 2, "tenure_days": 200}
    base.update(over)
    return base


def mkscore(cid="REC-1", p_nat=0.30, uplifts=None, segment="standard"):
    """Build a CaseScore with explicit uplift per action."""
    uplifts = uplifts or {}
    cs = CaseScore(case_id=cid, p_natural=p_nat, segment=segment,
                   failure_class="temporary_failure")
    for a in ACTIONS:
        u = 0.0 if a == "no_action" else uplifts.get(a, 0.0)
        cs.actions[a] = ActionScore(a, u, min(p_nat + u, 1.0), a in CONTACT_ACTIONS)
    return cs


# ===========================================================================
# Cost model
# ===========================================================================

def test_contact_actions_carry_annoyance_cost():
    assert action_cost("sms_payment_link", 40.0) == pytest.approx(40.25)
    assert action_cost("whatsapp_nudge", 40.0) == pytest.approx(40.85)


def test_retry_actions_do_not_carry_annoyance_cost():
    assert action_cost("retry_immediate", 40.0) == pytest.approx(2.00)
    assert action_cost("retry_delayed", 999.0) == pytest.approx(2.00)


def test_no_action_is_free():
    assert action_cost("no_action", 40.0) == 0.0


def test_annoyance_cost_is_a_parameter_not_a_constant():
    """It is swept in the sensitivity analysis, so it must be injectable."""
    assert action_cost("sms_payment_link", 0.0) == pytest.approx(0.25)
    assert action_cost("sms_payment_link", 900.0) == pytest.approx(900.25)


# ===========================================================================
# Incremental EV
# ===========================================================================

def test_incremental_ev_is_amount_times_uplift_minus_cost(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=10000.0)
    alts = alloc.score_alternatives(case, mkscore(uplifts={"sms_payment_link": 0.10}))
    sms = next(a for a in alts if a.action == "sms_payment_link")
    assert sms.incremental_ev == pytest.approx(10000.0 * 0.10 - 40.25)


def test_negative_uplift_produces_negative_ev(eng):
    alloc = Allocator(eng, 40.0)
    alts = alloc.score_alternatives(
        mkcase(), mkscore(uplifts={"sms_payment_link": -0.05}))
    sms = next(a for a in alts if a.action == "sms_payment_link")
    assert sms.incremental_ev < 0


def test_every_action_is_scored_and_kept(eng):
    """Rejected options are retained with their reason -- that table is the
    visible proof of the decision process."""
    alloc = Allocator(eng, 40.0)
    alts = alloc.score_alternatives(mkcase(), mkscore())
    assert len(alts) == len(ACTIONS)


# ===========================================================================
# The two EV floors -- trap 13.1
# ===========================================================================

def test_low_ev_retry_is_taken_but_low_ev_contact_is_not(eng):
    """A retry worth Rs 12 is clearly worth taking. A single Rs 50 floor applied
    to both would suppress it along with the contact."""
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=1000.0)
    # retry uplift 0.014 -> EV 12.00 ; contact uplift 0.06 -> EV 19.75
    score = mkscore(uplifts={"retry_delayed": 0.014, "sms_payment_link": 0.06})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=10)
    p = plans["REC-1"]
    assert p.action == "retry_delayed", "the profitable retry must survive"
    sms = next(a for a in p.alternatives if a.action == "sms_payment_link")
    assert sms.rejection_type == "ev_floor"
    assert "50.00 floor for contact actions" in sms.rejection_detail


def test_retry_below_the_zero_contact_floor_is_rejected(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=100.0)
    score = mkscore(uplifts={"retry_delayed": 0.001})   # EV = -1.90
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=10)
    assert plans["REC-1"].action == "no_action"


# ===========================================================================
# Marginal ranking -- the core of the thesis
# ===========================================================================

def test_contact_is_ranked_on_marginal_gain_not_absolute_value(eng):
    """The headline property. A Rs 50,000 payment whose contact adds only a
    little over a free retry must lose to a Rs 3,000 payment whose contact adds
    a lot."""
    alloc = Allocator(eng, 40.0)
    big = mkcase("REC-BIG", 50000.0)
    small = mkcase("REC-SMALL", 3000.0)
    scores = {
        # big: retry already earns 50000*0.020 = 1000; contact earns
        # 50000*0.0205 - 40.25 = 984.75 -> marginal is NEGATIVE
        "REC-BIG": mkscore("REC-BIG", uplifts={"retry_delayed": 0.020,
                                               "sms_payment_link": 0.0205}),
        # small: retry earns 3000*0.005 = 13; contact earns 3000*0.30 - 40.25
        # = 859.75 -> marginal +846.75
        "REC-SMALL": mkscore("REC-SMALL", uplifts={"retry_delayed": 0.005,
                                                   "sms_payment_link": 0.30}),
    }
    plans = alloc.plan_batch([big, small], scores, budget=1)
    assert plans["REC-SMALL"].won_contact is True
    assert plans["REC-BIG"].won_contact is False
    assert plans["REC-BIG"].action == "retry_delayed"


def test_budget_is_spent_on_the_highest_marginal_gains(eng):
    alloc = Allocator(eng, 40.0)
    cases, scores = [], {}
    for i in range(10):
        cid = f"REC-{i}"
        cases.append(mkcase(cid, 5000.0))
        scores[cid] = mkscore(cid, uplifts={"retry_delayed": 0.002,
                                            "sms_payment_link": 0.05 + i * 0.01})
    plans = alloc.plan_batch(cases, scores, budget=3)
    winners = {c for c, p in plans.items() if p.won_contact}
    assert winners == {"REC-9", "REC-8", "REC-7"}


def test_budget_is_not_exceeded(eng):
    alloc = Allocator(eng, 40.0)
    cases, scores = [], {}
    for i in range(40):
        cid = f"REC-{i}"
        cases.append(mkcase(cid, 8000.0))
        scores[cid] = mkscore(cid, uplifts={"sms_payment_link": 0.20})
    plans = alloc.plan_batch(cases, scores, budget=7)
    assert sum(p.won_contact for p in plans.values()) == 7


# ===========================================================================
# Recorded rejections -- computed, never prose labels
# ===========================================================================

def test_budget_losers_record_their_rank_and_the_cutoff(eng):
    alloc = Allocator(eng, 40.0)
    cases, scores = [], {}
    for i in range(6):
        cid = f"REC-{i}"
        cases.append(mkcase(cid, 8000.0))
        scores[cid] = mkscore(cid, uplifts={"sms_payment_link": 0.05 + i * 0.02})
    plans = alloc.plan_batch(cases, scores, budget=2)
    loser = plans["REC-0"]
    assert loser.budget_rank == 6
    assert loser.budget_contenders == 6
    assert loser.budget_cutoff_ev is not None
    alt = next(a for a in loser.alternatives if a.action == "sms_payment_link")
    assert alt.rejection_type == "budget_cutoff"
    assert "rank 6 of 6" in alt.rejection_detail


def test_policy_blocked_alternatives_name_the_rule(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(opted_out=True)
    alts = alloc.score_alternatives(case, mkscore(uplifts={"sms_payment_link": 0.3}))
    sms = next(a for a in alts if a.action == "sms_payment_link")
    assert sms.rejection_type == "policy"
    assert sms.blocked_by == "R3"
    assert "R3" in sms.rejection_detail


def test_every_rejection_carries_a_computed_reason(eng):
    """No rejection may be a qualitative label. Each must trace to a number or a
    named rule."""
    alloc = Allocator(eng, 40.0)
    cases, scores = [], {}
    for i in range(20):
        cid = f"REC-{i}"
        cases.append(mkcase(cid, 2000.0 + i * 900))
        scores[cid] = mkscore(cid, uplifts={"retry_delayed": 0.01 + i * 0.002,
                                            "sms_payment_link": 0.02 + i * 0.01,
                                            "whatsapp_nudge": 0.01})
    plans = alloc.plan_batch(cases, scores, budget=4)
    valid = {"ev_floor", "budget_cutoff", "policy", "lower_ev"}
    for p in plans.values():
        for a in p.alternatives:
            if a.selected or a.action == "no_action":
                continue
            assert a.rejection_type in valid, f"{a.action}: {a.rejection_type}"
            assert a.rejection_detail, f"{a.action} rejected with no detail"
            assert any(ch.isdigit() for ch in a.rejection_detail), (
                f"{a.action} rejection is qualitative: {a.rejection_detail!r}")


def test_exactly_one_alternative_is_selected(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase()
    score = mkscore(uplifts={"retry_delayed": 0.05, "sms_payment_link": 0.20})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=1)
    p = plans["REC-1"]
    assert sum(a.selected for a in p.alternatives) == 1
    assert next(a for a in p.alternatives if a.selected).action == p.action


# ===========================================================================
# Standby escalation candidate -- feeds trap 13.2
# ===========================================================================

def test_retry_plan_carries_a_standby_contact(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=5000.0)
    score = mkscore(uplifts={"retry_delayed": 0.10, "sms_payment_link": 0.03})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=0)
    p = plans["REC-1"]
    assert p.action == "retry_delayed"
    assert p.escalation_action == "sms_payment_link"


def test_case_that_won_a_contact_has_no_standby(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=9000.0)
    score = mkscore(uplifts={"retry_delayed": 0.005, "sms_payment_link": 0.25})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=1)
    p = plans["REC-1"]
    assert p.won_contact and p.escalation_action is None


def test_opted_out_case_gets_no_standby_contact(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(opted_out=True, amount=9000.0)
    score = mkscore(uplifts={"retry_delayed": 0.05, "sms_payment_link": 0.25})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=5)
    assert plans["REC-1"].escalation_action is None


# ===========================================================================
# Skipping
# ===========================================================================

def test_high_value_case_with_no_uplift_does_not_get_a_contact(eng):
    """The judgement moment: a large payment that was going to recover anyway.

    The correct behaviour is NOT to skip it entirely -- a retry costs Rs 2 and
    still has positive expected value, so declining it would be leaving money on
    the table. The correct behaviour is to decline the CONTACT, whose Rs 40
    annoyance cost the near-zero uplift cannot justify. That is exactly what the
    two separate EV floors exist to express.
    """
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=48000.0)
    score = mkscore(p_nat=0.95, uplifts={a: 0.0005 for a in ACTIONS})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=50)
    p = plans["REC-1"]
    assert not p.won_contact
    sms = next(a for a in p.alternatives if a.action == "sms_payment_link")
    assert sms.rejection_type == "ev_floor"
    assert p.action in ("retry_immediate", "retry_delayed")


def test_high_value_case_is_skipped_entirely_when_even_a_retry_loses(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=48000.0)
    score = mkscore(p_nat=0.97, uplifts={a: 0.00002 for a in ACTIONS})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=50)
    assert plans["REC-1"].action == "no_action"


def test_all_negative_uplift_case_is_skipped(eng):
    alloc = Allocator(eng, 40.0)
    case = mkcase(amount=20000.0)
    score = mkscore(uplifts={a: -0.05 for a in ACTIONS if a != "no_action"})
    plans = alloc.plan_batch([case], {case["case_id"]: score}, budget=50)
    assert plans["REC-1"].action == "no_action"
