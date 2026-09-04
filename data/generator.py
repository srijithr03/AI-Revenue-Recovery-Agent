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

from agent.constants import CONTACT_ACTIONS, METHODS, TREATMENT_ACTIONS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

N_CASES = 5000
N_HOLDOUT = 1000

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
FAILURE_CLASS_PRIOR = {
    "temporary_failure": 0.26,
    "insufficient_funds": 0.24,
    "authentication_failure": 0.20,
    "invalid_method": 0.13,
    "repeated_failure": 0.10,
    "risk_blocked": 0.07,
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

# A6 -- gateway error codes that map unambiguously to a cause.
GATEWAY_CODES = {
    "temporary_failure": ["GW_TIMEOUT", "BANK_UNAVAILABLE", "UPI_TXN_TIMEOUT", "GATEWAY_ERROR"],
    "insufficient_funds": ["INSUFFICIENT_FUNDS", "NO_BALANCE", "U31"],
    "invalid_method": ["CARD_EXPIRED", "INVALID_VPA", "ACCOUNT_CLOSED", "MANDATE_REVOKED"],
    "authentication_failure": ["OTP_TIMEOUT", "3DS_FAILED", "PIN_INCORRECT", "AUTH_ABANDONED"],
    "risk_blocked": ["RISK_DECLINED", "FRAUD_SUSPECTED", "VELOCITY_LIMIT"],
    "repeated_failure": ["REPEAT_DECLINE"],
}

UNMAPPED_CODE = "UNMAPPED"

# A7 -- free-text gateway messages for the ~15% ambiguous slice.  Written in the
# register real gateways actually use: vague, passive, and unhelpful.  Each
# still has a known true class, so diagnosis accuracy stays measurable.
AMBIGUOUS_MESSAGES = {
    "temporary_failure": [
        "The transaction could not be completed at this time. Please try again later.",
        "Unable to process request. The service is temporarily unable to respond.",
        "Payment not completed due to a connectivity issue at the bank end.",
        "Request failed. No response was received from the remote host.",
        "The operation did not complete. Please reattempt after some time.",
    ],
    "insufficient_funds": [
        "The issuing bank declined the transaction. Please contact your bank for details.",
        "Transaction not permitted on this account at this time.",
        "Your bank was unable to authorise this payment. Please try a different account.",
        "Payment declined by the account holder bank.",
    ],
    "invalid_method": [
        "The payer VPA is no longer active.",
        "The saved instrument can no longer be used for this payment.",
        "Account details on file could not be validated with the bank.",
        "This payment instrument is not in a usable state.",
    ],
    "authentication_failure": [
        "The customer did not complete the required verification step.",
        "Authorisation was not confirmed within the permitted time.",
        "Verification was not completed for this payment.",
        "The additional security check was not finished by the payer.",
    ],
    "risk_blocked": [
        "This transaction did not pass our internal checks.",
        "Payment could not be processed for this account.",
        "The request was stopped before reaching the bank.",
    ],
    "repeated_failure": [
        "Multiple recent attempts on this instrument have not succeeded.",
        "This payment has been declined on prior attempts as well.",
    ],
}

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

    # Customers who have already failed repeatedly are far more likely to be
    # failing for the same structural reason again.
    if prior_failures >= 3:
        weights["repeated_failure"] *= 4.0
        weights["invalid_method"] *= 1.6
        weights["temporary_failure"] *= 0.6
    elif prior_failures == 2:
        weights["repeated_failure"] *= 2.0

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
        if ambiguous:
            gateway_code = UNMAPPED_CODE
            gateway_message = str(rng.choice(AMBIGUOUS_MESSAGES[failure_class]))
        else:
            gateway_code = str(rng.choice(GATEWAY_CODES[failure_class]))
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
        }

    return cases, truth


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
    print("wrote data/cases.json, data/ground_truth.json, data/split.json")


if __name__ == "__main__":
    main()
