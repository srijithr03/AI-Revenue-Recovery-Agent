"""L0 -- Synthetic world generator.

Produces a population of failed payments with:

  * OBSERVABLE features, written to ``data/cases.json``
  * HIDDEN ground truth, written to ``data/ground_truth.json``

The two files are kept separate on disk on purpose. Nothing in ``agent/`` is
permitted to open ``ground_truth.json``; only the L0 simulator executor and the
L8 scorer may, and ``tests/test_ground_truth_boundary.py`` enforces it.

Design requirements this file is built to satisfy (spec Part 5.4):

  R1  p_natural is an INTERACTION of features, composed on the log-odds scale,
      not a per-class lookup.  Target population spread ~0.05 - 0.70.
  R2  Outcomes are SAMPLED, never deterministic.  Two identical cases can
      diverge.  (The sampling happens in the executor; the generator fixes the
      probabilities.)
  R3  Uplift is heterogeneous and includes genuinely NEGATIVE values, driven by
      a hidden annoyance-prone trait.  Target 8-12% of cases with a negative
      best-contact uplift.
  R4  ~15% of records carry unmapped free text, forcing the LLM path to matter.
  R5  Every base rate is documented in data/ASSUMPTIONS.md.
  R6  The whole world is reproducible from data/seed.txt.

Run:  python -m data.generator
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from agent.constants import (ACTIONS, CONTACT_ACTIONS, FAILURE_CLASSES,
                             METHODS, TREATMENT_ACTIONS)

FAILURE_CLASSES_ALL = tuple(FAILURE_CLASSES)
ACTIONS_ALL = tuple(ACTIONS)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

N_CASES = 16000
N_HOLDOUT = 12000

# IST -- the merchant local clock.  Quiet hours and "late night" are defined in
# this frame, so the generator and the policy engine must agree on it.
IST = timezone(timedelta(hours=5, minutes=30))

# ===========================================================================
# Base rates.  Every number here is an assumption; see data/ASSUMPTIONS.md.
# ===========================================================================

# A1 -- probability a failed payment recovers on its own, within a 72h window,
# before any feature adjustment.
BASE_NATURAL_RECOVERY = {
    "temporary_failure": 0.55,
    "insufficient_funds": 0.22,
    "invalid_method": 0.06,
    "authentication_failure": 0.34,
    "risk_blocked": 0.03,
    "repeated_failure": 0.08,
}

# A2 -- unconditional mix of failure causes.  Conditioned further on customer
# features below, so the realised mix differs from this prior.
#
# CALIBRATED against NPCI's published UPI decline split rather than assumed.
# NPCI reports two decline families monthly, bank-wise:
#
#   TD (technical decline)  -- bank / NPCI infrastructure.  Published system-wide
#                              at roughly 0.3-0.8% of all UPI transactions.
#   BD (business decline)   -- customer-side: insufficient balance, wrong PIN,
#                              expired mandate.  Target ceiling 5%.
#
#   Source: https://www.npci.org.in/what-we-do/upi/upi-ecosystem-statistics
#           https://ckandev.indiadataportal.com/dataset/national-payments-corporation-of-india-npci
#
# Taking TD ~0.4% against BD ~4.1%, TD is roughly 9% of UPI *failures* and BD
# roughly 91%.  Two corrections applied before using that split here:
#
#   1. NPCI's TD is narrowly bank/NPCI-side.  It excludes gateway- and PSP-side
#      timeouts, which a merchant's failed-payment queue sees as transient too.
#      So 9% is a LOWER bound on `temporary_failure`, not the value.
#   2. This batch is not UPI-only (A3), and card failures skew harder toward
#      instrument problems than UPI does.
#
# Net effect versus the previous uncalibrated guess: `temporary_failure` falls
# 0.26 -> 0.19 and `insufficient_funds` rises 0.24 -> 0.31, because NPCI's data
# says business declines dominate by roughly ten to one and insufficient balance
# is the largest single BD cause.  Both moves make the world HARDER for the
# agent: the class with the highest natural recovery gets rarer, and the class
# where retry-timing matters most gets commoner.
FAILURE_CLASS_PRIOR = {
    "temporary_failure": 0.19,
    "insufficient_funds": 0.31,
    "authentication_failure": 0.22,
    "invalid_method": 0.12,
    "repeated_failure": 0.10,
    "risk_blocked": 0.06,
}

# A3 -- payment method mix, weighted toward UPI as is typical for Indian
# consumer merchants.
METHOD_WEIGHTS = {"upi": 0.62, "card": 0.24, "netbanking": 0.09, "wallet": 0.05}

# A4 -- treatment effects as MULTIPLIERS ON THE ODDS of recovery, per
# (failure class, action).  Values below 1.0 mean the action actively hurts:
# it burns an attempt, or annoys, without addressing the cause.
ODDS_MULTIPLIER = {
    "temporary_failure": {
        "retry_immediate": 1.35,        # may fire before the transient clears
        "retry_delayed": 2.30,          # the right move: give it time
        "sms_payment_link": 1.45,
        "whatsapp_nudge": 1.50,
        "method_update_request": 0.95,  # nothing wrong with the method
        "human_escalation": 1.60,
    },
    "insufficient_funds": {
        "retry_immediate": 0.80,        # balance has not changed in 200ms
        "retry_delayed": 1.55,
        "sms_payment_link": 2.10,       # lets them pay once funded
        "whatsapp_nudge": 1.95,
        "method_update_request": 1.40,  # switch to a funded instrument
        "human_escalation": 2.20,
    },
    "invalid_method": {
        "retry_immediate": 0.70,        # will fail identically, every time
        "retry_delayed": 0.75,
        "sms_payment_link": 1.80,
        "whatsapp_nudge": 1.85,
        "method_update_request": 4.20,  # the only action that fixes the cause
        "human_escalation": 3.10,
    },
    "authentication_failure": {
        "retry_immediate": 1.90,        # re-prompting the OTP genuinely works
        "retry_delayed": 1.65,
        "sms_payment_link": 2.05,
        "whatsapp_nudge": 1.90,
        "method_update_request": 1.05,
        "human_escalation": 2.00,
    },
    "risk_blocked": {
        "retry_immediate": 0.85,        # the risk engine will decline again
        "retry_delayed": 0.90,
        "sms_payment_link": 1.05,
        "whatsapp_nudge": 1.05,
        "method_update_request": 1.30,
        "human_escalation": 3.40,       # manual review is the only real path
    },
    "repeated_failure": {
        "retry_immediate": 0.75,
        "retry_delayed": 0.95,
        "sms_payment_link": 1.50,
        "whatsapp_nudge": 1.55,
        "method_update_request": 2.60,
        "human_escalation": 2.40,
    },
}

# A5 -- hidden annoyance trait.  Contact actions on an annoyance-prone customer
# get their odds multiplied down by this factor, which is what produces
# genuinely negative uplift.
#
# Applied to ALL contact actions, human escalation included.  An earlier version
# exempted escalation, which meant the BEST contact action was never negative and
# the agent never faced a case where staying silent was the right call.  The
# property check in data/verify_world.py caught that.
ANNOYANCE_ODDS_MULTIPLIER = 0.25

# P(annoyance_prone) conditioned on the OBSERVABLE fragile segment.  Note this
# is probabilistic, not a rule: the agent can learn the average effect over the
# segment but can never identify the trait per-customer.  That gap is the
# irreducible error that keeps the evaluation from being circular.
P_ANNOYANCE_GIVEN_FRAGILE = 0.38
P_ANNOYANCE_GIVEN_NOT_FRAGILE = 0.035

# A9 -- share of the batch drawn from chronically-failing instruments.  A batch
# of FAILED payments is not a random sample of customers: instruments that fail
# are over-represented precisely because they keep failing.  Modelling this as a
# mixture is what makes the fragile segment large enough to matter.
P_CHRONIC_FAILER = 0.22
P_NEW_CUSTOMER = 0.22

# A6 -- gateway error codes.
#
# These are Razorpay's DOCUMENTED payment error reasons, not invented strings,
# and they are keyed by METHOD because the real taxonomy is method-specific:
# `card_declined` does not exist on a UPI payment and `invalid_vpa` does not
# exist on a card.  Sources:
#   https://razorpay.com/docs/errors/payments/upi/
#   https://razorpay.com/docs/errors/payments/cards/
#
# Two structural consequences, both deliberate and both realistic:
#
#   1. `repeated_failure` has NO code under any method.  No gateway emits
#      "this is the fifth consecutive failure on this instrument" -- it reports
#      the proximate symptom, every time.  That class is therefore reachable
#      only from customer history, which is exactly what the L1 contradiction
#      rule reads.  Under the previous invented taxonomy a `REPEAT_DECLINE`
#      code existed and made the class trivially readable; it does not exist in
#      any real gateway and it has been removed.
#
#   2. UPI's published taxonomy has no dedicated risk/fraud reason.  A UPI risk
#      block surfaces as the generic `payment_declined`, while cards get the
#      specific `payment_risk_check_failed`.  That asymmetry is real, and it is
#      why `payment_declined` is diagnosed at reduced confidence in L1.
GATEWAY_CODES: dict[str, dict[str, list[str]]] = {
    "upi": {
        "temporary_failure": ["bank_technical_error", "gateway_technical_error",
                              "payment_timed_out"],
        "insufficient_funds": ["insufficient_funds"],
        "invalid_method": ["invalid_vpa", "vpa_resolution_failed"],
        "authentication_failure": ["payment_cancelled",
                                   "payment_collect_request_expired"],
        "risk_blocked": ["payment_declined"],
    },
    "card": {
        "temporary_failure": ["gateway_technical_error", "bank_technical_error",
                              "payment_timed_out"],
        "insufficient_funds": ["insufficient_funds", "transaction_limit_exceeded"],
        "invalid_method": ["card_expired", "card_not_enrolled",
                           "card_disabled_for_online_payments",
                           "debit_instrument_inactive", "debit_instrument_blocked"],
        "authentication_failure": ["authentication_failed", "incorrect_cvv",
                                   "payment_cancelled"],
        "risk_blocked": ["payment_risk_check_failed"],
    },
    "netbanking": {
        "temporary_failure": ["bank_technical_error", "gateway_technical_error",
                              "payment_timed_out"],
        "insufficient_funds": ["insufficient_funds"],
        "invalid_method": ["debit_instrument_inactive"],
        "authentication_failure": ["authentication_failed", "payment_cancelled"],
        "risk_blocked": ["payment_risk_check_failed"],
    },
    "wallet": {
        "temporary_failure": ["gateway_technical_error", "payment_timed_out"],
        "insufficient_funds": ["insufficient_funds"],
        "invalid_method": ["debit_instrument_inactive"],
        "authentication_failure": ["authentication_failed", "payment_cancelled"],
        "risk_blocked": ["payment_risk_check_failed"],
    },
}

# The genuinely uninformative reason a gateway falls back to when it cannot
# classify the failure.  `payment_failed` is Razorpay's documented catch-all
# ("general bank decline"), and it is deliberately absent from CODE_TO_CLASS:
# it carries no diagnostic content, so it routes to the LLM path with nothing
# but free text and customer history to work from.  The ~15% ambiguous slice
# rides on this rather than on an invented "UNMAPPED" sentinel.
UNMAPPED_CODE = "payment_failed"

# A7 -- free-text gateway messages for the ~15% ambiguous slice.  Written in the
# register real gateways actually use: vague, passive, and unhelpful.
#
# Each entry declares the SET of true causes that can produce it.  Messages
# whose set has more than one member are genuinely ambiguous from the text
# alone -- "the issuing bank declined the transaction" is what a gateway says
# for an empty balance, a risk hold, AND a dead card.
#
# This is the property that makes the LLM path do real work.  A regex sees only
# the string and must guess the modal class; a model that is also given the
# customer history (prior failures, tenure, risk score) can resolve which cause
# is actually in play.  The final entry is resolvable by nothing, and exists so
# that abstaining with `unknown` is sometimes the only correct answer.
AMBIGUOUS_MESSAGE_POOL: list[tuple[str, tuple[str, ...]]] = [
    # -- genuinely ambiguous: the same sentence, several different causes -----
    ("The issuing bank declined the transaction. Please contact your bank for details.",
     ("insufficient_funds", "risk_blocked", "invalid_method", "repeated_failure")),
    ("Transaction not permitted on this account at this time.",
     ("insufficient_funds", "risk_blocked", "invalid_method")),
    ("The transaction could not be completed at this time. Please try again later.",
     ("temporary_failure", "authentication_failure")),
    ("Payment could not be processed. Please try a different payment method.",
     ("invalid_method", "insufficient_funds", "repeated_failure")),
    ("The request was not completed.",
     ("temporary_failure", "authentication_failure", "risk_blocked")),
    ("We were unable to process this payment at this time.",
     ("temporary_failure", "insufficient_funds", "risk_blocked")),
    ("Your bank was unable to authorise this payment.",
     ("insufficient_funds", "authentication_failure", "risk_blocked")),
    ("The operation did not complete. Please reattempt after some time.",
     ("temporary_failure", "authentication_failure", "repeated_failure")),

    # -- resolvable from the text alone ---------------------------------------
    ("Unable to process request. The service is temporarily unable to respond.",
     ("temporary_failure",)),
    ("Request failed. No response was received from the remote host.",
     ("temporary_failure",)),
    ("The customer did not complete the required verification step.",
     ("authentication_failure",)),
    ("Authorisation was not confirmed within the permitted time.",
     ("authentication_failure",)),
    ("The payer VPA is no longer active.",
     ("invalid_method",)),
    ("The saved instrument can no longer be used for this payment.",
     ("invalid_method",)),
    ("Your account has insufficient balance to complete this transaction.",
     ("insufficient_funds",)),
    ("This transaction did not pass our internal checks.",
     ("risk_blocked",)),
    ("Multiple recent attempts on this instrument have not succeeded.",
     ("repeated_failure",)),

    # -- resolvable by nothing: the correct answer here is to abstain ---------
    ("This payment did not go through. No further details are available.",
     FAILURE_CLASSES_ALL),
]

# A8 -- merchant categories, descriptive colour on the case record.
MERCHANT_CATEGORIES = ["subscription", "ecommerce", "edtech", "travel", "utilities", "gaming"]


# ===========================================================================
# Helpers
# ===========================================================================

def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def read_seed() -> int:
    with open(os.path.join(HERE, "seed.txt")) as fh:
        return int(fh.read().strip())


# ===========================================================================
# Generation
# ===========================================================================

def _draw_failure_class(rng: np.random.Generator, prior_failures: int,
                        tenure_days: int, risk_latent: float) -> str:
    """Draw a failure cause, conditioned on customer features.

    Conditioning matters: it means failure class is CONFOUNDED with the
    features that also drive natural recovery. A model that ignores the
    confounding will mis-attribute, which is exactly the realism we want.
    """
    weights = dict(FAILURE_CLASS_PRIOR)

    # `repeated_failure` is close to definitional: it MEANS the nth consecutive
    # failure on the same instrument.  So it is largely determined by the prior
    # failure count rather than drawn freely.  The residual mass at high counts
    # is the genuine case where something new went wrong on an account that also
    # happens to have a bad history -- a real transient outage on a chronic
    # failer.  That residual is what stops the L1 contradiction rule from being
    # a free win.
    if prior_failures >= 4:
        weights["repeated_failure"] *= 21.0
        weights["invalid_method"] *= 1.6
        weights["temporary_failure"] *= 0.6
    elif prior_failures == 3:
        weights["repeated_failure"] *= 6.0
        weights["invalid_method"] *= 1.6
        weights["temporary_failure"] *= 0.7
    elif prior_failures == 2:
        weights["repeated_failure"] *= 2.5
    elif prior_failures == 1:
        # One prior failure does not yet make a pattern.
        weights["repeated_failure"] *= 0.30
    else:
        # A17 -- `repeated_failure` is DEFINITIONALLY impossible with no prior
        # failures on the instrument. The class means "the nth consecutive
        # failure"; with n = 1 there is nothing being repeated.
        #
        # This was a real defect, found by the diagnostic error analysis rather
        # than by reading the code: the class kept its full base weight at
        # prior_failures == 0, so 137 training cases were labelled
        # `repeated_failure` with no failure to repeat. They were undiagnosable
        # by construction -- no observable feature could identify them, because
        # the label contradicted the only feature that defines it -- and they
        # capped recall on the class at a level no agent could reach.
        #
        # Removing them makes the world COHERENT, not easier in the sense that
        # matters: no signal is added, and nothing that was genuinely ambiguous
        # becomes clear. But it does raise measured accuracy, so it is reported
        # as a world fix and not as an agent improvement.
        weights["repeated_failure"] = 0.0

    # Brand-new customers skew toward setup problems, not transient ones.
    if tenure_days < 30:
        weights["invalid_method"] *= 1.5
        weights["authentication_failure"] *= 1.3
        weights["repeated_failure"] *= 0.4

    # Latent risk drives risk-engine blocks.
    weights["risk_blocked"] *= 1.0 + 6.0 * risk_latent

    total = sum(weights.values())
    keys = list(weights)
    probs = [weights[k] / total for k in keys]
    return str(rng.choice(keys, p=probs))


def _p_natural(rng: np.random.Generator, failure_class: str, amount: float,
               prior_success: int, prior_failures: int, tenure_days: int,
               hour: int) -> float:
    """Requirement 1: an interaction on the log-odds scale, not a lookup."""
    z = logit(BASE_NATURAL_RECOVERY[failure_class])

    # Loyal customers come back and retry on their own.  Saturating.
    z += 0.16 * min(prior_success, 8)

    # Customers who have already failed repeatedly do not.  Saturating, and
    # weighted more heavily than success -- failure is the stronger signal.
    z -= 0.26 * min(prior_failures, 8)

    # Tenure: a long relationship survives a payment hiccup.
    z += 0.45 * min(tenure_days, 720) / 720.0

    # Late-night failures stall rather than resolve -- the customer is asleep,
    # and by morning the purchase intent has cooled.
    if hour >= 22 or hour <= 5:
        z -= 0.40

    # Big-ticket hesitation: the larger the amount, the more likely the failure
    # becomes a reconsideration rather than a retry.
    z -= 0.45 * min(max(math.log10(max(amount, 1.0)) - 3.0, 0.0), 1.5)

    # Unexplained variance.  Without this the world is a deterministic function
    # of its own features and any model can invert it exactly.
    z += float(rng.normal(0.0, 0.55))

    return float(np.clip(sigmoid(z), 0.02, 0.88))


def _p_treated(p_nat: float, failure_class: str, annoyance_prone: bool,
               rng: np.random.Generator) -> dict[str, float]:
    """Requirement 3: heterogeneous, per-case treatment effects on the odds."""
    base_odds = p_nat / (1 - p_nat)
    out: dict[str, float] = {"no_action": p_nat}

    for action in TREATMENT_ACTIONS:
        mult = ODDS_MULTIPLIER[failure_class][action]

        # Per-case jitter on the log-multiplier, so two cases in the same cell
        # do not share an identical treatment effect.
        mult *= float(math.exp(rng.normal(0.0, 0.18)))

        # The annoyance trait: contacting a customer who reacts badly to being
        # contacted makes recovery LESS likely, not more.
        if annoyance_prone and action in CONTACT_ACTIONS:
            mult *= ANNOYANCE_ODDS_MULTIPLIER

        odds = base_odds * mult
        out[action] = float(np.clip(odds / (1 + odds), 0.005, 0.97))

    return out


def generate(n: int = N_CASES, seed: int | None = None
             ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Generate ``n`` cases.  Returns (observable_cases, ground_truth_by_id)."""
    if seed is None:
        seed = read_seed()
    rng = np.random.default_rng(seed)

    now = datetime(2026, 3, 14, 9, 0, 0, tzinfo=IST)

    cases: list[dict[str, Any]] = []
    truth: dict[str, dict[str, Any]] = {}

    for i in range(n):
        case_id = f"REC-{1000 + i}"

        # ---- customer history ----------------------------------------------
        # Tenure is a mixture: an established base plus a genuine cohort of
        # brand-new customers, who fail differently and recover differently.
        if rng.random() < P_NEW_CUSTOMER:
            tenure_days = int(rng.uniform(0, 50))
        else:
            tenure_days = int(np.clip(rng.gamma(shape=1.6, scale=150), 0, 1800))

        # Prior successes scale with tenure -- a two-year customer has bought
        # before.  Poisson keeps the tail sensible.
        prior_success = int(rng.poisson(0.9 + 5.0 * min(tenure_days, 720) / 720.0))

        # Prior failures are a mixture, not a single Poisson.  See A9: a batch of
        # failed payments over-represents instruments that fail chronically.
        if rng.random() < P_CHRONIC_FAILER:
            prior_failures = int(np.clip(rng.poisson(3.0), 0, 9))
        else:
            prior_failures = int(np.clip(rng.poisson(0.6), 0, 9))

        risk_latent = float(rng.beta(1.4, 9.0))  # skewed low, long right tail

        # ---- the failure -----------------------------------------------------
        amount = round(float(np.clip(rng.lognormal(mean=math.log(2500), sigma=1.10),
                                     99, 120000)), 2)

        method = str(rng.choice(list(METHOD_WEIGHTS), p=list(METHOD_WEIGHTS.values())))

        # Hour of failure: bimodal, with an evening peak, in IST.
        if rng.random() < 0.62:
            hour = int(np.clip(rng.normal(20.0, 2.6), 0, 23))
        else:
            hour = int(np.clip(rng.normal(12.0, 4.0), 0, 23))

        failure_class = _draw_failure_class(rng, prior_failures, tenure_days, risk_latent)

        # Risk score is observable and correlates with, but does not determine,
        # a risk block.
        if failure_class == "risk_blocked":
            risk_score = float(np.clip(rng.beta(6.0, 2.2), 0, 1))
        else:
            risk_score = float(np.clip(risk_latent + rng.normal(0, 0.06), 0, 1))
        risk_score = round(risk_score, 3)

        # ---- gateway signal ---------------------------------------------------
        # Requirement 4: ~15% carry unmapped free text only.
        ambiguous = bool(rng.random() < 0.15)
        misleading_code = False
        if ambiguous:
            gateway_code = UNMAPPED_CODE
            options = [m for m, cls in AMBIGUOUS_MESSAGE_POOL if failure_class in cls]
            gateway_message = options[int(rng.integers(len(options)))]
        else:
            # A15 -- a gateway reports the PROXIMATE symptom, not the actionable
            # cause.  A card that has failed five times running still returns
            # `insufficient_funds` on the sixth attempt; the code is accurate and
            # the diagnosis it implies is wrong.  Retrying is pointless, and a
            # method update is the move.  Modelling this is what gives the
            # contradictory-signal rule (L1) something real to catch.
            #
            # Under the real Razorpay taxonomy this is not a 65% tendency but a
            # certainty: no gateway has a "repeated failure" reason at all (A6),
            # so the class ALWAYS presents as something else and is reachable
            # only from customer history.
            if failure_class == "repeated_failure":
                symptom = str(rng.choice(
                    ["insufficient_funds", "invalid_method", "authentication_failure"],
                    p=[0.50, 0.30, 0.20]))
                gateway_code = str(rng.choice(GATEWAY_CODES[method][symptom]))
                misleading_code = True
            else:
                gateway_code = str(rng.choice(GATEWAY_CODES[method][failure_class]))

            # A16 -- generic-decline leakage.  UPI has no dedicated risk reason,
            # so every UPI risk block already surfaces as the bare
            # `payment_declined` (A6).  But that same bare reason is also what a
            # bank returns when it declines for a cause that DOES have its own
            # code -- it simply chose not to be specific.  Without this leakage
            # `payment_declined` would be perfectly diagnostic of a risk block in
            # this world, which is precisely the kind of accidental giveaway that
            # makes a synthetic evaluation circular.  Measured at 15%, the modal
            # cause of `payment_declined` stays risk_blocked at roughly 0.6 --
            # low-information, as a generic reason should be.
            if (method == "upi"
                    and failure_class in ("insufficient_funds", "invalid_method")
                    and rng.random() < 0.15):
                gateway_code = "payment_declined"

            gateway_message = ""

        # ---- compliance flags -------------------------------------------------
        opted_out = bool(rng.random() < 0.05)
        disputed = bool(rng.random() < 0.02)

        # ---- age ---------------------------------------------------------------
        age_hours = float(round(rng.uniform(0.1, 80.0), 2))
        failed_at = now - timedelta(hours=age_hours)

        # ---- hidden ground truth ------------------------------------------------
        p_nat = _p_natural(rng, failure_class, amount, prior_success,
                           prior_failures, tenure_days, hour)

        observably_fragile = prior_failures >= 3 or tenure_days < 30
        p_ann = P_ANNOYANCE_GIVEN_FRAGILE if observably_fragile else P_ANNOYANCE_GIVEN_NOT_FRAGILE
        annoyance_prone = bool(rng.random() < p_ann)

        p_treated = _p_treated(p_nat, failure_class, annoyance_prone, rng)

        cases.append({
            "case_id": case_id,
            "amount": amount,
            "method": method,
            "gateway_code": gateway_code,
            "gateway_message": gateway_message,
            "tenure_days": tenure_days,
            "prior_success": prior_success,
            "prior_failures": prior_failures,
            "hour": hour,
            "risk_score": risk_score,
            "opted_out": opted_out,
            "disputed": disputed,
            "failed_at": failed_at.isoformat(),
            "age_hours": age_hours,
            "merchant_category": str(rng.choice(MERCHANT_CATEGORIES)),
        })

        truth[case_id] = {
            "p_natural": round(p_nat, 6),
            "p_treated": {k: round(v, 6) for k, v in p_treated.items()},
            "true_failure_class": failure_class,
            "annoyance_prone": annoyance_prone,
            "ambiguous": ambiguous,
            "misleading_code": misleading_code,
        }

    return cases, truth


# ===========================================================================
# Historical exploration log
# ===========================================================================
#
# What a merchant actually has is not a set of probabilities -- it is a pile of
# past failed payments, each with an action that was taken and a binary outcome
# that was observed.  This function produces exactly that, and it is the ONLY
# thing the agent is fitted on.
#
# Actions are assigned at random, which is what makes the log an exploration
# log rather than a confounded observational one: because assignment is
# independent of the hidden probabilities, the difference in outcome rates
# between treated and untreated cells is an unbiased estimate of uplift.
#
# The log is drawn from a DIFFERENT seed than the evaluation world, so no
# evaluation case appears in it.

HISTORY_SEED_OFFSET = 7717
N_HISTORY = 25000


def generate_history(n: int = N_HISTORY, seed: int | None = None
                     ) -> list[dict[str, Any]]:
    """Past failed payments with a randomised action and an OBSERVED outcome.

    The returned records carry no probabilities. Only ``action_taken`` and
    ``recovered`` are added to the observable case fields.
    """
    if seed is None:
        seed = read_seed()
    cases, truth = generate(n, seed + HISTORY_SEED_OFFSET)
    rng = np.random.default_rng(seed + HISTORY_SEED_OFFSET + 1)

    log: list[dict[str, Any]] = []
    for case in cases:
        t = truth[case["case_id"]]
        action = str(rng.choice(list(ACTIONS_ALL)))
        # R2: the outcome is SAMPLED, never assigned deterministically.
        recovered = bool(rng.random() < t["p_treated"][action])
        rec = dict(case)
        rec["case_id"] = "HIST-" + case["case_id"].split("-")[1]
        rec["action_taken"] = action
        rec["recovered"] = recovered
        log.append(rec)
    return log


def split_ids(cases: list[dict[str, Any]], seed: int,
              n_holdout: int = N_HOLDOUT) -> dict[str, list[str]]:
    """Hold out ``n_holdout`` cases.  Everything fitted is fitted on the rest."""
    rng = np.random.default_rng(seed + 991)
    ids = [c["case_id"] for c in cases]
    idx = rng.permutation(len(ids))
    holdout = sorted(ids[i] for i in idx[:n_holdout])
    train = sorted(ids[i] for i in idx[n_holdout:])
    return {"train": train, "holdout": holdout}


def main() -> None:
    seed = read_seed()
    cases, truth = generate(N_CASES, seed)
    split = split_ids(cases, seed)

    with open(os.path.join(HERE, "cases.json"), "w") as fh:
        json.dump(cases, fh, indent=1)
    with open(os.path.join(HERE, "ground_truth.json"), "w") as fh:
        json.dump(truth, fh, indent=1)
    with open(os.path.join(HERE, "split.json"), "w") as fh:
        json.dump(split, fh, indent=1)

    print(f"seed              {seed}")
    print(f"cases             {len(cases)}")
    print(f"train / holdout   {len(split['train'])} / {len(split['holdout'])}")
    history = generate_history(N_HISTORY, seed)
    with open(os.path.join(HERE, "history.json"), "w") as fh:
        json.dump(history, fh, indent=1)

    hrec = sum(h["recovered"] for h in history)
    print(f"history log        {len(history)} records, "
          f"{hrec / len(history):.1%} observed recovery")
    print("wrote data/cases.json, data/ground_truth.json, data/split.json, "
          "data/history.json")


if __name__ == "__main__":
    main()
