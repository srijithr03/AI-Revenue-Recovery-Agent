"""Sensitivity analysis.

Two sweeps, over the two parameters the headline result actually depends on.

  1. ANNOYANCE COST (A10) -- the single most load-bearing assumption in the
     project, and one with no published value. Rather than defend a number,
     sweep it and report how each arm responds. The expected and defensible
     finding is that the agent withdraws contacts as they become expensive
     while the naive bot keeps sending regardless.

  2. CONTACT BUDGET (A14) -- the agent is constrained to 150 contacts per 1,000
     cases; the naive arm is not constrained at all. Sweeping the budget answers
     the obvious question a panel will ask: is the agent behind because its
     targeting is no good, or because it is being made to fight with one hand
     tied? Those are very different findings and the sweep separates them.
"""

from __future__ import annotations

from typing import Any

from eval.harness import CONTACT_BUDGET_PER_1000, Harness, compare_paired

ANNOYANCE_POINTS = (0.0, 40.0, 150.0, 400.0, 900.0)
BUDGET_POINTS = (75, 150, 300, 600, 1200, 3000)


def sweep_annoyance(cases: list[dict[str, Any]], model: Any,
                    diagnoses: dict[str, Any], seed: int,
                    points: tuple[float, ...] = ANNOYANCE_POINTS
                    ) -> list[dict[str, Any]]:
    """Re-run all three arms at each annoyance cost."""
    rows: list[dict[str, Any]] = []
    for cost in points:
        h = Harness(annoyance_cost=cost, seed=seed, quiet=True)
        res = h.run_paired(cases, model, diagnoses)["results"]
        cmp_ = compare_paired(res)
        rows.append({
            "annoyance_cost": cost,
            "control_net_per_case": round(res["control"].net_per_case, 2),
            "naive_net_per_case": round(res["naive"].net_per_case, 2),
            "agent_net_per_case": round(res["agent"].net_per_case, 2),
            "naive_contacts": res["naive"].contacts,
            "agent_contacts": res["agent"].contacts,
            "agent_vs_control": cmp_["agent_vs_control"]["net_per_case"],
            "naive_vs_control": cmp_["naive_vs_control"]["net_per_case"],
            "agent_vs_naive": cmp_["agent_vs_naive"]["net_per_case"],
            "agent_vs_naive_ci": cmp_["agent_vs_naive"]["ci"],
            "agent_wins": cmp_["agent_vs_naive"]["net_per_case"] > 0,
            "agent_net_per_contact": cmp_["net_incremental_per_contact"]["agent"],
            "naive_net_per_contact": cmp_["net_incremental_per_contact"]["naive"],
        })
    return rows


def sweep_budget(cases: list[dict[str, Any]], model: Any,
                 diagnoses: dict[str, Any], seed: int,
                 points: tuple[int, ...] = BUDGET_POINTS) -> list[dict[str, Any]]:
    """Re-run the agent at several contact budgets, against a fixed naive arm.

    The naive arm does not move -- it has no budget concept -- so its line is
    flat and the agent crosses it (or does not) at some contact volume.
    """
    import eval.harness as H

    rows: list[dict[str, Any]] = []
    original = H.CONTACT_BUDGET_PER_1000
    try:
        for b in points:
            H.CONTACT_BUDGET_PER_1000 = b
            h = Harness(seed=seed, quiet=True)
            res = h.run_paired(cases, model, diagnoses)["results"]
            cmp_ = compare_paired(res)
            rows.append({
                "budget_per_1000": b,
                "agent_contacts": res["agent"].contacts,
                "naive_contacts": res["naive"].contacts,
                "agent_net_per_case": round(res["agent"].net_per_case, 2),
                "naive_net_per_case": round(res["naive"].net_per_case, 2),
                "agent_vs_naive": cmp_["agent_vs_naive"]["net_per_case"],
                "agent_vs_naive_ci": cmp_["agent_vs_naive"]["ci"],
                "agent_wins": cmp_["agent_vs_naive"]["net_per_case"] > 0,
                "agent_net_per_contact": cmp_["net_incremental_per_contact"]["agent"],
            })
    finally:
        H.CONTACT_BUDGET_PER_1000 = original
    return rows
