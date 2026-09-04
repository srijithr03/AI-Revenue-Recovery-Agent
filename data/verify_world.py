"""Generator property checks (spec Part 5.4 / Build Order step 2).

These run BEFORE anything is built on top of the world. If the world is too
easy or too uniform, every downstream number is decoration.

Run:  python -m data.verify_world
Exit code is non-zero if any hard gate fails.
"""

from __future__ import annotations

import json
import os
from collections import Counter

import numpy as np

from agent.constants import CONTACT_ACTIONS, FAILURE_CLASSES

HERE = os.path.dirname(os.path.abspath(__file__))

# Hard gates.  A failure here means the world must be retuned, not that the
# agent is bad.
GATES = {
    "p_natural_p05_max": 0.15,     # 5th pct must sit low
    "p_natural_p95_min": 0.55,     # 95th pct must sit high -> real spread
    "neg_uplift_share_lo": 0.08,   # spec target 8-12%
    "neg_uplift_share_hi": 0.12,
    "ambiguous_share_lo": 0.13,
    "ambiguous_share_hi": 0.17,
}


def load():
    with open(os.path.join(HERE, "cases.json")) as fh:
        cases = json.load(fh)
    with open(os.path.join(HERE, "ground_truth.json")) as fh:
        truth = json.load(fh)
    return cases, truth


def main() -> int:
    cases, truth = load()
    n = len(cases)
    failures: list[str] = []

    print("=" * 72)
    print("GENERATOR PROPERTY VERIFICATION")
    print("=" * 72)

    # ---------------------------------------------------------------- R1 spread
    p_nat = np.array([truth[c["case_id"]]["p_natural"] for c in cases])
    p05, p25, p50, p75, p95 = np.percentile(p_nat, [5, 25, 50, 75, 95])
    print("\nR1  p_natural spread (target ~0.05 - 0.70)")
    print(f"    min {p_nat.min():.3f}  p05 {p05:.3f}  p25 {p25:.3f}  "
          f"median {p50:.3f}  p75 {p75:.3f}  p95 {p95:.3f}  max {p_nat.max():.3f}")
    print(f"    mean {p_nat.mean():.3f}   sd {p_nat.std():.3f}")
    if p05 > GATES["p_natural_p05_max"]:
        failures.append(f"p_natural p05={p05:.3f} too high (want <= {GATES['p_natural_p05_max']})")
    if p95 < GATES["p_natural_p95_min"]:
        failures.append(f"p_natural p95={p95:.3f} too low (want >= {GATES['p_natural_p95_min']})")

    # p_natural must NOT be a per-class lookup: within-class variance must be
    # a meaningful share of total variance.
    print("\n    within-class spread (proves interaction, not lookup)")
    by_class: dict[str, list[float]] = {k: [] for k in FAILURE_CLASSES}
    for c in cases:
        t = truth[c["case_id"]]
        by_class[t["true_failure_class"]].append(t["p_natural"])
    within = []
    for k in FAILURE_CLASSES:
        arr = np.array(by_class[k])
        within.append(arr.var())
        print(f"      {k:24} n={len(arr):5d}  mean {arr.mean():.3f}  "
              f"sd {arr.std():.3f}  [{arr.min():.3f}, {arr.max():.3f}]")
    within_var = float(np.average(within, weights=[len(by_class[k]) for k in FAILURE_CLASSES]))
    ratio = within_var / p_nat.var()
    print(f"      within-class variance / total variance = {ratio:.3f}")
    if ratio < 0.25:
        failures.append(f"p_natural is close to a per-class lookup (ratio {ratio:.3f} < 0.25)")

    # ---------------------------------------------------------------- R3 uplift
    print("\nR3  uplift heterogeneity")
    best_contact_uplift = []
    any_neg_contact = 0
    for c in cases:
        t = truth[c["case_id"]]
        pn = t["p_natural"]
        ups = [t["p_treated"][a] - pn for a in CONTACT_ACTIONS]
        best_contact_uplift.append(max(ups))
        if min(ups) < 0:
            any_neg_contact += 1
    bcu = np.array(best_contact_uplift)
    neg_share = float((bcu < 0).mean())
    print(f"    best-contact uplift: mean {bcu.mean():+.3f}  sd {bcu.std():.3f}  "
          f"min {bcu.min():+.3f}  max {bcu.max():+.3f}")
    print(f"    cases where the BEST contact action has negative uplift: "
          f"{neg_share:.1%}  (target {GATES['neg_uplift_share_lo']:.0%}-"
          f"{GATES['neg_uplift_share_hi']:.0%})")
    print(f"    cases where at least one contact action has negative uplift: "
          f"{any_neg_contact / n:.1%}")
    if not (GATES["neg_uplift_share_lo"] <= neg_share <= GATES["neg_uplift_share_hi"]):
        failures.append(f"negative best-contact uplift share {neg_share:.1%} outside "
                        f"[{GATES['neg_uplift_share_lo']:.0%}, {GATES['neg_uplift_share_hi']:.0%}]")

    # Actions must genuinely differ in usefulness by failure class.
    print("\n    mean uplift by (failure class, action) -- the structure the agent must learn")
    acts = ["retry_immediate", "retry_delayed", "sms_payment_link",
            "whatsapp_nudge", "method_update_request", "human_escalation"]
    print(f"      {'class':24}" + "".join(f"{a[:11]:>13}" for a in acts))
    for k in FAILURE_CLASSES:
        row = []
        for a in acts:
            vals = [truth[c["case_id"]]["p_treated"][a] - truth[c["case_id"]]["p_natural"]
                    for c in cases if truth[c["case_id"]]["true_failure_class"] == k]
            row.append(float(np.mean(vals)))
        print(f"      {k:24}" + "".join(f"{v:>+13.3f}" for v in row))

    # ---------------------------------------------------------------- R4 ambiguity
    amb = sum(1 for c in cases if truth[c["case_id"]]["ambiguous"])
    amb_share = amb / n
    print(f"\nR4  ambiguous free-text records: {amb} / {n} = {amb_share:.1%}  "
          f"(target ~15%)")
    if not (GATES["ambiguous_share_lo"] <= amb_share <= GATES["ambiguous_share_hi"]):
        failures.append(f"ambiguous share {amb_share:.1%} outside target band")

    # ---------------------------------------------------------------- population
    print("\nPopulation shape")
    amt = np.array([c["amount"] for c in cases])
    print(f"    amount: median Rs {np.median(amt):,.0f}  mean Rs {amt.mean():,.0f}  "
          f"p95 Rs {np.percentile(amt, 95):,.0f}  max Rs {amt.max():,.0f}")
    print(f"    total at risk: Rs {amt.sum():,.0f}")
    cc = Counter(truth[c["case_id"]]["true_failure_class"] for c in cases)
    for k, v in cc.most_common():
        print(f"    {k:24} {v:5d}  {v / n:6.1%}")
    print(f"    opted_out {sum(c['opted_out'] for c in cases) / n:.1%}   "
          f"disputed {sum(c['disputed'] for c in cases) / n:.1%}   "
          f"risk>=0.7 {sum(c['risk_score'] >= 0.7 for c in cases) / n:.1%}")
    quiet = sum(1 for c in cases if c["hour"] >= 21 or c["hour"] < 9)
    print(f"    failed during quiet hours (21:00-09:00 IST): {quiet / n:.1%}")

    # ---------------------------------------------------------------- verdict
    print("\n" + "=" * 72)
    if failures:
        print("GATES FAILED")
        for f in failures:
            print(f"  x {f}")
        print("=" * 72)
        return 1
    print("ALL GATES PASSED -- the world is hard enough to build on.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
