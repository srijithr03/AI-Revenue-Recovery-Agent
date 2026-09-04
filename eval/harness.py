"""L8 -- Three-arm evaluation harness.

    control   no action at all           -> the counterfactual
    naive     retry 3x, then contact     -> what an ordinary retry bot achieves
    agent     uplift-ranked, budgeted    -> the system under test

Beating control proves the system does something. Beating naive proves the
system is intelligent. The second comparison is the one almost no competing
submission includes, and it is the one that can invalidate a flattering result.

The naive arm is deliberately NOT weakened. It gets the same policy engine, the
same compliance rules, and the same sequential escalation structure. The only
thing it lacks is targeting -- which is precisely the variable under test.

Everything is compared on NET value: recovered revenue minus intervention cost.
Gross recovery charges nothing for retries or contacts, so it systematically
flatters any maximalist strategy and penalises the agent for the restraint it
was built to exercise.

Run:  python -m eval.harness
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from agent.audit import AuditTrail
from agent.constants import ARMS, CONTACT_ACTIONS, FAILURE_CLASSES
from agent.diagnosis import Diagnosis, LLMDiagnoser, diagnose_batch
from agent.executors.razorpay_test import RazorpayTestExecutor
from agent.executors.simulator import SimulatorExecutor
from agent.policy import PolicyEngine
from agent.state_machine import BudgetTracker, CaseOutcome, StateMachine
from agent.uplift import UpliftModel, load_history
from agent.valuation import Allocator, Plan, DEFAULT_ANNOYANCE_COST
from eval.stats import bootstrap_diff, bootstrap_mean, crosses_zero, wilson

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RESULTS = os.path.join(HERE, "results")

# Contacts permitted per 1,000 cases in an arm. Scaled to arm size so the three
# arms are compared on the same per-case footing.
CONTACT_BUDGET_PER_1000 = 150

VALUE_BANDS = ((0.0, 2000.0, "under_2k"),
               (2000.0, 15000.0, "2k_15k"),
               (15000.0, float("inf"), "above_15k"))


def value_band(amount: float) -> str:
    for lo, hi, name in VALUE_BANDS:
        if lo <= amount < hi:
            return name
    return "above_15k"


# ===========================================================================

@dataclass
class ArmResult:
    arm: str
    n: int = 0
    outcomes: list[CaseOutcome] = field(default_factory=list)
    net_per_case_values: list[float] = field(default_factory=list)

    # headline aggregates
    gross_recovered: float = 0.0
    total_cost: float = 0.0
    confirmed: int = 0
    payment_success: int = 0
    attempted: int = 0
    contacts: int = 0
    budget: int = 0
    at_risk: float = 0.0

    def add(self, case: dict[str, Any], out: CaseOutcome) -> None:
        self.outcomes.append(out)
        self.n += 1
        self.at_risk += float(case["amount"])
        self.gross_recovered += out.amount_confirmed
        self.total_cost += out.cost_spent
        self.confirmed += int(out.confirmed)
        self.payment_success += int(out.payment_success)
        self.attempted += int(out.attempted)
        self.contacts += out.contacts
        self.net_per_case_values.append(out.amount_confirmed - out.cost_spent)

    # ---- derived -------------------------------------------------------

    @property
    def net(self) -> float:
        return self.gross_recovered - self.total_cost

    @property
    def net_per_case(self) -> float:
        return self.net / self.n if self.n else 0.0

    @property
    def recovery_rate(self) -> float:
        return self.confirmed / self.n if self.n else 0.0

    def summary(self) -> dict[str, Any]:
        p, lo, hi = wilson(self.confirmed, self.n)
        m, mlo, mhi = bootstrap_mean(self.net_per_case_values)
        states = Counter(o.state for o in self.outcomes)
        stops = Counter(o.stop_reason.split(":")[0].split("(")[0].strip()
                        for o in self.outcomes if o.stop_reason)
        return {
            "arm": self.arm,
            "n": self.n,
            "at_risk": round(self.at_risk, 2),
            "gross_recovered": round(self.gross_recovered, 2),
            "total_cost": round(self.total_cost, 2),
            "net": round(self.net, 2),
            "net_per_case": round(self.net_per_case, 2),
            "net_per_case_ci": [round(mlo, 2), round(mhi, 2)],
            "recovery_rate": round(p, 4),
            "recovery_rate_ci": [round(lo, 4), round(hi, 4)],
            "attempted": self.attempted,
            "payment_success": self.payment_success,
            "confirmed": self.confirmed,
            "contacts": self.contacts,
            "budget": self.budget,
            "net_per_contact": (round(self.net / self.contacts, 2)
                                if self.contacts else None),
            "states": dict(states),
            "stop_reasons": dict(stops.most_common()),
            "escalated_sequentially": sum(o.escalated_sequentially
                                          for o in self.outcomes),
            "deferrals": sum(o.deferrals for o in self.outcomes),
        }


# ===========================================================================

class Harness:
    def __init__(self, annoyance_cost: float = DEFAULT_ANNOYANCE_COST,
                 seed: int = 0, quiet: bool = False) -> None:
        self.annoyance_cost = annoyance_cost
        self.seed = seed
        self.quiet = quiet
        self.engine = PolicyEngine()
        # One trail PER ARM. Sharing a single trail keyed by case id meant that
        # in the paired design a case accumulated control, naive and agent
        # events interleaved in one log -- which reads as a single incoherent
        # sequence and is exactly the kind of thing an audit trail must not do.
        self.trails: dict[str, AuditTrail] = {a: AuditTrail() for a in ARMS}
        self.trail = self.trails["agent"]
        self.policy_violations = 0
        self.plans: dict[str, Plan] = {}

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, flush=True)

    # ---------------------------------------------------------------- assign

    @staticmethod
    def stratified_assign(cases: list[dict[str, Any]],
                          diagnoses: dict[str, Diagnosis],
                          seed: int) -> dict[str, str]:
        """Randomise within strata of (predicted failure class x value band).

        Stratifying on the PREDICTED class, not the true one, keeps ground truth
        entirely out of the experiment design -- and is what a merchant running
        this for real could actually do.

        Unstratified assignment risks handing one arm the easy cases by chance
        and rendering the delta meaningless. It is cheap to do and expensive to
        omit.
        """
        rng = np.random.default_rng(seed + 4242)
        strata: dict[tuple[str, str], list[str]] = defaultdict(list)
        for c in cases:
            key = (diagnoses[c["case_id"]].failure_class, value_band(c["amount"]))
            strata[key].append(c["case_id"])

        assignment: dict[str, str] = {}
        for key in sorted(strata):
            ids = sorted(strata[key])
            order = rng.permutation(len(ids))
            # Deal round-robin through a shuffled stratum so arm sizes stay
            # balanced even in strata that are not divisible by three.
            offset = int(rng.integers(0, 3))
            for i, pos in enumerate(order):
                assignment[ids[pos]] = ARMS[(i + offset) % 3]
        return assignment

    # ---------------------------------------------------------------- arms

    def run_control(self, cases: list[dict[str, Any]],
                    executor: SimulatorExecutor) -> ArmResult:
        """No action at all. This is the counterfactual, and it is the number
        the entire industry reports without measuring."""
        res = ArmResult("control")
        res.budget = 0
        from agent.verification import verify
        for case in cases:
            nat = executor.observe_no_action(case)
            v = verify(case, False, nat.success,
                       float(case.get("age_hours", 0.0)),
                       StateMachine._is_reversed(case["case_id"]))
            out = CaseOutcome(case_id=case["case_id"], arm="control",
                              state="INELIGIBLE", stop_reason="control arm: no action",
                              payment_success=v.payment_success,
                              confirmed=v.confirmed,
                              amount_confirmed=v.amount_confirmed,
                              execution_mode="simulated")
            trail = self.trails["control"]
            trail.append(case["case_id"], "SCORED", "rules",
                         "control arm: no action taken", "INELIGIBLE")
            if v.confirmed:
                trail.append(case["case_id"], "RECOVERED", "verifier",
                             f"recovered naturally, {v.amount_confirmed:.2f}, "
                             f"with no action taken", "INELIGIBLE")
            res.add(case, out)
        return res

    def run_naive(self, cases: list[dict[str, Any]],
                  diagnoses: dict[str, Diagnosis],
                  executor: SimulatorExecutor) -> ArmResult:
        """Retry up to three times, then contact every customer who has not
        opted out. No uplift reasoning, no budget, no targeting.

        This is deliberately what a normal retry bot does. It is not weakened to
        make the agent look good: it keeps the full policy engine, the same
        compliance rules, and the same escalation structure.
        """
        res = ArmResult("naive")
        res.budget = 0  # unconstrained by design
        budget = BudgetTracker(10 ** 9)
        sm = StateMachine(self.engine, executor, self.trails["naive"], budget,
                          self.annoyance_cost, respect_budget=False)
        for case in cases:
            plan = Plan(case_id=case["case_id"], action="retry_immediate",
                        escalation_action="sms_payment_link",
                        failure_class=diagnoses[case["case_id"]].failure_class)
            out = sm.run_case(case, diagnoses[case["case_id"]], plan, "naive")
            res.add(case, out)
        res.contacts = sum(o.contacts for o in res.outcomes)
        return res

    def run_agent(self, cases: list[dict[str, Any]],
                  diagnoses: dict[str, Diagnosis], model: UpliftModel,
                  executor: SimulatorExecutor) -> ArmResult:
        """The full pipeline: diagnose, score uplift, value, allocate under a
        binding contact budget, gate on policy, execute, escalate, verify."""
        res = ArmResult("agent")
        budget_n = max(1, round(CONTACT_BUDGET_PER_1000 * len(cases) / 1000))
        res.budget = budget_n

        scores = {c["case_id"]: model.score(c, diagnoses[c["case_id"]].failure_class)
                  for c in cases}
        alloc = Allocator(self.engine, self.annoyance_cost)
        plans = alloc.plan_batch(cases, scores, budget=budget_n)
        self.plans.update(plans)

        budget = BudgetTracker(budget_n)
        sm = StateMachine(self.engine, executor, self.trails["agent"], budget,
                          self.annoyance_cost, respect_budget=True)
        for case in cases:
            out = sm.run_case(case, diagnoses[case["case_id"]],
                              plans[case["case_id"]], "agent")
            res.add(case, out)
        res.contacts = sum(o.contacts for o in res.outcomes)
        return res

    # ---------------------------------------------------------------- run

    def run(self, cases: list[dict[str, Any]], model: UpliftModel,
            diagnoses: dict[str, Diagnosis]) -> dict[str, Any]:
        t0 = time.perf_counter()

        assignment = self.stratified_assign(cases, diagnoses, self.seed)
        by_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
        for c in cases:
            by_arm[assignment[c["case_id"]]].append(c)

        self.log(f"  assignment: " +
                 "  ".join(f"{a} {len(by_arm[a])}" for a in ARMS))

        executor = SimulatorExecutor(seed=self.seed)
        results = {
            "control": self.run_control(by_arm["control"], executor),
            "naive": self.run_naive(by_arm["naive"], diagnoses, executor),
            "agent": self.run_agent(by_arm["agent"], diagnoses, model, executor),
        }

        duration = time.perf_counter() - t0
        return {"results": results, "assignment": assignment,
                "duration": duration, "by_arm": by_arm}

    # ---------------------------------------------------------------- paired

    def run_paired(self, cases: list[dict[str, Any]], model: UpliftModel,
                   diagnoses: dict[str, Diagnosis]) -> dict[str, Any]:
        """Run EVERY case through ALL THREE arms with the same latent draw.

        This is the true counterfactual, and it is only obtainable because the
        world is synthetic: a merchant cannot both contact a customer and not
        contact them. It is reported alongside the randomised comparison, never
        instead of it, and it is labelled as simulation-only everywhere it
        appears.

        Statistically it is far more powerful. Between-case variance dominates
        the randomised design -- amounts span Rs 99 to Rs 1,20,000, so the
        recovery of one large payment moves an arm mean more than the entire
        treatment effect. Pairing differences that away.
        """
        t0 = time.perf_counter()
        # Each arm gets its own executor instance so that applied-action state
        # does not leak between arms, but the latent draw per case is derived
        # from the case id and is therefore identical across all three.
        out = {
            "control": self.run_control(cases, SimulatorExecutor(seed=self.seed)),
            "naive": self.run_naive(cases, diagnoses,
                                    SimulatorExecutor(seed=self.seed)),
            "agent": self.run_agent(cases, diagnoses, model,
                                    SimulatorExecutor(seed=self.seed)),
        }
        return {"results": out, "duration": time.perf_counter() - t0}


# ===========================================================================
# Comparison
# ===========================================================================

def compare(results: dict[str, ArmResult]) -> dict[str, Any]:
    ctrl, naive, agent = results["control"], results["naive"], results["agent"]

    a_vs_c = bootstrap_diff(agent.net_per_case_values, ctrl.net_per_case_values)
    n_vs_c = bootstrap_diff(naive.net_per_case_values, ctrl.net_per_case_values)
    a_vs_n = bootstrap_diff(agent.net_per_case_values, naive.net_per_case_values)

    # Gross, reported separately and never as the headline.
    g_a = (agent.gross_recovered / agent.n) - (ctrl.gross_recovered / ctrl.n)
    g_n = (naive.gross_recovered / naive.n) - (ctrl.gross_recovered / ctrl.n)

    def per_contact(arm: ArmResult, delta_net_per_case: float) -> float | None:
        if not arm.contacts:
            return None
        return delta_net_per_case * arm.n / arm.contacts

    return {
        "agent_vs_control": {
            "net_per_case": round(a_vs_c[0], 2),
            "ci": [round(a_vs_c[1], 2), round(a_vs_c[2], 2)],
            "significant": not crosses_zero(a_vs_c[1], a_vs_c[2]),
            "gross_per_case": round(g_a, 2),
        },
        "naive_vs_control": {
            "net_per_case": round(n_vs_c[0], 2),
            "ci": [round(n_vs_c[1], 2), round(n_vs_c[2], 2)],
            "significant": not crosses_zero(n_vs_c[1], n_vs_c[2]),
            "gross_per_case": round(g_n, 2),
        },
        "agent_vs_naive": {
            "net_per_case": round(a_vs_n[0], 2),
            "ci": [round(a_vs_n[1], 2), round(a_vs_n[2], 2)],
            "significant": not crosses_zero(a_vs_n[1], a_vs_n[2]),
            "agent_beats_naive": a_vs_n[0] > 0,
        },
        "net_incremental_per_contact": {
            "agent": (round(per_contact(agent, a_vs_c[0]), 2)
                      if agent.contacts else None),
            "naive": (round(per_contact(naive, n_vs_c[0]), 2)
                      if naive.contacts else None),
        },
    }


def compare_paired(results: dict[str, ArmResult]) -> dict[str, Any]:
    """Paired comparison. Requires all arms to have run the same cases in the
    same order, which run_paired guarantees."""
    from eval.stats import bootstrap_paired_diff
    ctrl, naive, agent = results["control"], results["naive"], results["agent"]

    order_ok = ([o.case_id for o in agent.outcomes]
                == [o.case_id for o in ctrl.outcomes]
                == [o.case_id for o in naive.outcomes])
    if not order_ok:
        raise RuntimeError("paired comparison requires identical case ordering")

    a_c = bootstrap_paired_diff(agent.net_per_case_values, ctrl.net_per_case_values)
    n_c = bootstrap_paired_diff(naive.net_per_case_values, ctrl.net_per_case_values)
    a_n = bootstrap_paired_diff(agent.net_per_case_values, naive.net_per_case_values)

    return {
        "design": "paired counterfactual (simulation only)",
        "n": agent.n,
        "agent_vs_control": {
            "net_per_case": round(a_c[0], 2),
            "ci": [round(a_c[1], 2), round(a_c[2], 2)],
            "significant": not crosses_zero(a_c[1], a_c[2]),
        },
        "naive_vs_control": {
            "net_per_case": round(n_c[0], 2),
            "ci": [round(n_c[1], 2), round(n_c[2], 2)],
            "significant": not crosses_zero(n_c[1], n_c[2]),
        },
        "agent_vs_naive": {
            "net_per_case": round(a_n[0], 2),
            "ci": [round(a_n[1], 2), round(a_n[2], 2)],
            "significant": not crosses_zero(a_n[1], a_n[2]),
            "agent_beats_naive": a_n[0] > 0,
        },
        "net_incremental_per_contact": {
            "agent": (round(a_c[0] * agent.n / agent.contacts, 2)
                      if agent.contacts else None),
            "naive": (round(n_c[0] * naive.n / naive.contacts, 2)
                      if naive.contacts else None),
        },
    }


def recovery_by_class(results: dict[str, ArmResult], truth: dict[str, Any]
                      ) -> dict[str, dict[str, Any]]:
    """Per-class recovery rate in each arm, keyed on TRUE class.

    This is a reporting-side use of ground truth by the scorer, which is
    permitted. Nothing in agent/ can reach it.
    """
    out: dict[str, dict[str, Any]] = {}
    for cls in FAILURE_CLASSES:
        row: dict[str, Any] = {}
        for arm, res in results.items():
            ids = [o for o in res.outcomes
                   if truth[o.case_id]["true_failure_class"] == cls]
            n = len(ids)
            k = sum(1 for o in ids if o.confirmed)
            p, lo, hi = wilson(k, n)
            row[arm] = {"n": n, "recovered": k, "rate": round(p, 4),
                        "ci": [round(lo, 4), round(hi, 4)]}
        out[cls] = row
    return out
