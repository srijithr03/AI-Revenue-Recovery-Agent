"""L2 -- Uplift scoring.

The distinction this layer exists to enforce:

    response  = P(recover | action)
    uplift    = P(recover | action) - P(recover | no action)

A response model ranks a Rs 20,000 payment with a 95% natural recovery rate
first. An uplift model correctly ranks it near last, because intervening on it
adds nothing. That single difference is what makes "better decisions, not more
retries" a claim rather than a slogan.

WHAT THIS LAYER IS ALLOWED TO SEE
---------------------------------
Only ``data/history.json`` -- a log of past failed payments with a randomised
action and an observed binary outcome. It never sees ``p_natural``,
``p_treated``, ``true_failure_class`` or ``annoyance_prone``. It does not even
see the true class of the historical cases: it runs them through L1 first and
keys everything on the PREDICTED class, exactly as it must at inference time.

Because actions in the log were assigned at random, the difference in observed
recovery rates between a treated cell and its untreated counterpart is an
unbiased estimate of that cell's average uplift.

IMPLEMENTATION CHOICE
---------------------
Option B from the spec: a structured, inspectable table keyed by
(predicted failure class, customer segment, action), with shrinkage toward zero
for thin cells. Zero is the right prior -- it means "no evidence this helps".

The do-nothing baseline is a logistic regression on the untreated slice, which
is a linear model in log-odds over twelve features whose coefficients are
printed by ``make uplift-report``. Both halves are defensible cold, which was
the deciding criterion: a learned model that cannot be explained under
questioning is worse than a transparent table that can.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from agent.constants import ACTIONS, CONTACT_ACTIONS, DIAGNOSIS_OUTPUTS, SEGMENTS, segment_of

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

# Shrinkage strength. A cell with SHRINKAGE_K observations is pulled halfway
# toward the prior. Set from the median cell size in the historical log.
SHRINKAGE_K = 40.0

# Clamp on the agent's own p_natural estimate.
P_NAT_MIN, P_NAT_MAX = 0.01, 0.92


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(x, 30.0), -30.0)))


# ---------------------------------------------------------------------------
# Features -- observable only
# ---------------------------------------------------------------------------

def feature_row(case: dict[str, Any], failure_class: str) -> list[float]:
    """Design matrix row. Every term is computable from the case record alone."""
    hour = int(case.get("hour", 12))
    amount = float(case.get("amount", 0.0))
    row = [1.0]
    row += [1.0 if failure_class == c else 0.0 for c in DIAGNOSIS_OUTPUTS]
    seg = segment_of(int(case.get("prior_success", 0)),
                     int(case.get("prior_failures", 0)),
                     int(case.get("tenure_days", 0)))
    row += [1.0 if seg == s else 0.0 for s in SEGMENTS]
    row.append(min(int(case.get("prior_success", 0)), 8) / 8.0)
    row.append(min(int(case.get("prior_failures", 0)), 8) / 8.0)
    row.append(min(int(case.get("tenure_days", 0)), 720) / 720.0)
    row.append(1.0 if (hour >= 22 or hour <= 5) else 0.0)
    row.append(min(max(math.log10(max(amount, 1.0)) - 3.0, 0.0), 1.5) / 1.5)
    row.append(float(case.get("risk_score", 0.0)))
    return row


FEATURE_NAMES = (["intercept"]
                 + [f"class={c}" for c in DIAGNOSIS_OUTPUTS]
                 + [f"segment={s}" for s in SEGMENTS]
                 + ["prior_success", "prior_failures", "tenure",
                    "late_night", "log_amount", "risk_score"])


@dataclass
class ActionScore:
    action: str
    uplift: float
    p_treated: float
    consumes_contact: bool


@dataclass
class CaseScore:
    case_id: str
    p_natural: float
    segment: str
    failure_class: str
    actions: dict[str, ActionScore] = field(default_factory=dict)


class UpliftModel:
    """Fitted on the historical exploration log. Never on the evaluation world."""

    def __init__(self) -> None:
        self.coef: np.ndarray | None = None
        self.table: dict[tuple[str, str, str], float] = {}
        self.cell_counts: dict[tuple[str, str, str], int] = {}
        self.class_action_mean: dict[tuple[str, str], float] = {}
        self.global_action_mean: dict[str, float] = {}
        self.n_fit = 0

    # ---------------------------------------------------------------- fitting

    def fit(self, log: list[dict[str, Any]], diagnoses: dict[str, Any]) -> "UpliftModel":
        """Fit from (case, predicted class, action taken, observed outcome)."""
        self.n_fit = len(log)

        rows, ys = [], []
        for rec in log:
            if rec["action_taken"] != "no_action":
                continue
            cls = diagnoses[rec["case_id"]].failure_class
            rows.append(feature_row(rec, cls))
            ys.append(1.0 if rec["recovered"] else 0.0)

        X = np.asarray(rows, dtype=float)
        y = np.asarray(ys, dtype=float)
        self.coef = self._fit_logistic(X, y)

        # ---- observed recovery rates per cell -----------------------------
        sums: dict[tuple[str, str, str], list[float]] = {}
        for rec in log:
            cls = diagnoses[rec["case_id"]].failure_class
            seg = segment_of(int(rec["prior_success"]), int(rec["prior_failures"]),
                             int(rec["tenure_days"]))
            key = (cls, seg, rec["action_taken"])
            s = sums.setdefault(key, [0.0, 0.0])
            s[0] += 1.0 if rec["recovered"] else 0.0
            s[1] += 1.0

        rate = {k: v[0] / v[1] for k, v in sums.items() if v[1] > 0}
        count = {k: int(v[1]) for k, v in sums.items()}

        # ---- coarser backoffs, for cells with little or no data -----------
        by_class_action: dict[tuple[str, str], list[float]] = {}
        by_action: dict[str, list[float]] = {}
        for (cls, seg, act), v in sums.items():
            ca = by_class_action.setdefault((cls, act), [0.0, 0.0])
            ca[0] += v[0]; ca[1] += v[1]
            a = by_action.setdefault(act, [0.0, 0.0])
            a[0] += v[0]; a[1] += v[1]
        class_action_rate = {k: v[0] / v[1] for k, v in by_class_action.items() if v[1] > 0}
        action_rate = {k: v[0] / v[1] for k, v in by_action.items() if v[1] > 0}

        # ---- uplift per cell, with shrinkage toward zero -------------------
        for cls in DIAGNOSIS_OUTPUTS:
            for seg in SEGMENTS:
                base_key = (cls, seg, "no_action")
                base = rate.get(base_key)
                base_n = count.get(base_key, 0)
                if base is None:
                    base = class_action_rate.get((cls, "no_action"),
                                                 action_rate.get("no_action", 0.3))
                for act in ACTIONS:
                    if act == "no_action":
                        continue
                    key = (cls, seg, act)
                    self.cell_counts[key] = count.get(key, 0)
                    treated = rate.get(key)
                    n = count.get(key, 0)
                    if treated is None:
                        treated = class_action_rate.get((cls, act))
                        n = 0
                    if treated is None:
                        self.table[key] = 0.0
                        continue
                    raw = treated - base
                    # Shrink toward zero. A cell backed by 5 observations should
                    # not move a rupee; a cell backed by 400 should.
                    eff_n = min(n, base_n) if base_n else n
                    w = eff_n / (eff_n + SHRINKAGE_K)
                    self.table[key] = float(raw * w)

        self.class_action_mean = {
            (c, a): class_action_rate.get((c, a), 0.0)
            for c in DIAGNOSIS_OUTPUTS for a in ACTIONS}
        self.global_action_mean = dict(action_rate)
        return self

    @staticmethod
    def _fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0,
                      iters: int = 300) -> np.ndarray:
        """Newton-Raphson with L2. Small and explicit, so there is no question
        about what it does or what it was trained on."""
        n, d = X.shape
        w = np.zeros(d)
        for _ in range(iters):
            z = np.clip(X @ w, -30, 30)
            p = 1.0 / (1.0 + np.exp(-z))
            grad = X.T @ (p - y) + l2 * w
            s = np.clip(p * (1 - p), 1e-6, None)
            H = (X * s[:, None]).T @ X + l2 * np.eye(d)
            try:
                step = np.linalg.solve(H, grad)
            except np.linalg.LinAlgError:
                break
            w -= step
            if np.max(np.abs(step)) < 1e-8:
                break
        return w

    # ---------------------------------------------------------------- scoring

    def estimate_p_natural(self, case: dict[str, Any], failure_class: str) -> float:
        """The agent's OWN estimate of the do-nothing baseline.

        Deliberately imperfect. It is fitted from binary outcomes on a finite
        log, so it cannot recover the generator's p_natural exactly, and the
        residual error is realistic rather than a defect.
        """
        assert self.coef is not None, "model not fitted"
        x = np.asarray(feature_row(case, failure_class), dtype=float)
        return float(np.clip(_sigmoid(float(x @ self.coef)), P_NAT_MIN, P_NAT_MAX))

    def score(self, case: dict[str, Any], failure_class: str) -> CaseScore:
        seg = segment_of(int(case.get("prior_success", 0)),
                         int(case.get("prior_failures", 0)),
                         int(case.get("tenure_days", 0)))
        p_nat = self.estimate_p_natural(case, failure_class)

        cs = CaseScore(case_id=case["case_id"], p_natural=p_nat, segment=seg,
                       failure_class=failure_class)
        cs.actions["no_action"] = ActionScore("no_action", 0.0, p_nat, False)

        for act in ACTIONS:
            if act == "no_action":
                continue
            u = self.table.get((failure_class, seg, act), 0.0)
            cs.actions[act] = ActionScore(
                action=act,
                uplift=float(u),
                p_treated=float(np.clip(p_nat + u, 0.0, 1.0)),
                consumes_contact=act in CONTACT_ACTIONS,
            )
        return cs

    # ---------------------------------------------------------------- report

    def report(self) -> str:
        out = [f"Uplift model -- fitted on {self.n_fit:,} historical records", ""]
        out.append("p_natural logistic coefficients (log-odds):")
        assert self.coef is not None
        for name, c in sorted(zip(FEATURE_NAMES, self.coef),
                              key=lambda t: -abs(t[1])):
            out.append(f"    {name:26} {c:+.3f}")
        out.append("")
        out.append("uplift table (shrunk), by predicted class x segment x action:")
        acts = [a for a in ACTIONS if a != "no_action"]
        out.append("    " + " " * 34 + "".join(f"{a[:11]:>13}" for a in acts))
        for cls in DIAGNOSIS_OUTPUTS:
            for seg in SEGMENTS:
                cells = [self.table.get((cls, seg, a), 0.0) for a in acts]
                ns = [self.cell_counts.get((cls, seg, a), 0) for a in acts]
                if not any(ns):
                    continue
                out.append(f"    {cls:24}{seg:10}" + "".join(f"{v:>+13.3f}" for v in cells))
                out.append(f"    {'':24}{'n=':>10}" + "".join(f"{n:>13d}" for n in ns))
        return "\n".join(out)


# ---------------------------------------------------------------------------

def load_history() -> list[dict[str, Any]]:
    with open(os.path.join(DATA, "history.json")) as fh:
        return json.load(fh)


def fit_from_history(llm=None) -> UpliftModel:
    """Fit the model end to end: diagnose the log, then fit on predicted classes."""
    from agent.diagnosis import LLMDiagnoser, diagnose_batch
    log = load_history()
    diags = diagnose_batch(log, llm or LLMDiagnoser())
    return UpliftModel().fit(log, diags)
