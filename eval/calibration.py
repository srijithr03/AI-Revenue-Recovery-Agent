"""Calibration measurement.

Two reliability checks, both possible only because ground truth exists:

  1. DIAGNOSIS CONFIDENCE.  When L1 says it is 93% sure, is it right 93% of the
     time? Bucket the predicted confidence, compute observed accuracy inside
     each bucket, and compare against the diagonal.

  2. UPLIFT.  When L2 predicts +0.15 uplift for the selected action, is the
     true uplift for that action on those cases about +0.15? This is the
     stronger of the two checks, because uplift is the quantity every decision
     is made on, and because a well-calibrated uplift model is what separates a
     system that reasons about causality from one that reasons about
     correlation.

Both are scorer-side. Neither result is fed back into the agent.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from eval.stats import wilson

CONFIDENCE_BUCKETS = [(0.0, 0.35), (0.35, 0.45), (0.45, 0.60), (0.60, 0.75),
                      (0.75, 0.85), (0.85, 0.95), (0.95, 1.01)]


def diagnosis_reliability(diagnoses: dict[str, Any], truth: dict[str, Any]
                          ) -> list[dict[str, Any]]:
    """Predicted confidence against observed accuracy, per bucket."""
    buckets: dict[tuple[float, float], list[tuple[float, bool]]] = defaultdict(list)
    for cid, d in diagnoses.items():
        if cid not in truth:
            continue
        # Abstentions are excluded. `unknown` is never a true class, so scoring
        # it as a wrong answer would put a guaranteed-0% bucket on the plot and
        # make a correctly-cautious system look badly calibrated. The abstention
        # RATE is reported separately instead, which is the honest treatment.
        if d.failure_class == "unknown":
            continue
        correct = d.failure_class == truth[cid]["true_failure_class"]
        for lo, hi in CONFIDENCE_BUCKETS:
            if lo <= d.confidence < hi:
                buckets[(lo, hi)].append((d.confidence, correct))
                break

    rows = []
    for (lo, hi) in CONFIDENCE_BUCKETS:
        items = buckets.get((lo, hi), [])
        if not items:
            continue
        n = len(items)
        k = sum(1 for _, c in items if c)
        p, clo, chi = wilson(k, n)
        rows.append({
            "bucket": f"{lo:.2f}-{hi:.2f}",
            "n": n,
            "mean_predicted": round(float(np.mean([c for c, _ in items])), 4),
            "observed_accuracy": round(p, 4),
            "ci": [round(clo, 4), round(chi, 4)],
            "gap": round(p - float(np.mean([c for c, _ in items])), 4),
        })
    return rows


def uplift_reliability(plans: dict[str, Any], truth: dict[str, Any],
                       n_buckets: int = 8) -> list[dict[str, Any]]:
    """Predicted uplift against TRUE uplift for the action actually selected.

    True uplift comes from the generator: p_treated[selected] - p_natural. It is
    read here, in the scorer, and nowhere else.
    """
    pairs: list[tuple[float, float]] = []
    for cid, plan in plans.items():
        if cid not in truth or plan.action == "no_action":
            continue
        t = truth[cid]
        true_u = t["p_treated"][plan.action] - t["p_natural"]
        pairs.append((plan.uplift, true_u))

    if not pairs:
        return []

    pred = np.array([p for p, _ in pairs])
    true = np.array([t for _, t in pairs])
    order = np.argsort(pred)
    chunks = np.array_split(order, n_buckets)

    rows = []
    for ch in chunks:
        if ch.size == 0:
            continue
        rows.append({
            "n": int(ch.size),
            "mean_predicted": round(float(pred[ch].mean()), 4),
            "mean_true": round(float(true[ch].mean()), 4),
            "gap": round(float(true[ch].mean() - pred[ch].mean()), 4),
        })

    # A single summary number: how much of the variation in true uplift the
    # predictions actually track.
    if pred.std() > 0 and true.std() > 0:
        corr = float(np.corrcoef(pred, true)[0, 1])
    else:
        corr = 0.0
    rows.append({"summary": True, "correlation": round(corr, 4),
                 "mean_predicted": round(float(pred.mean()), 4),
                 "mean_true": round(float(true.mean()), 4),
                 "n": int(pred.size)})
    return rows
