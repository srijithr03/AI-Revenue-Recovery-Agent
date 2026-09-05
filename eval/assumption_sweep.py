"""Assumption-error sweep -- does the conclusion survive the world being wrong?

The sweeps in eval/sensitivity.py vary what the AGENT believes: the annoyance
cost it charges itself, the contact budget it is given. Those are decision
parameters, and they move the agent inside a fixed world.

This file varies the WORLD. It perturbs the two generator assumptions with no
published value -- how often a failed payment comes back on its own, and how
much an intervention actually helps -- regenerates the population and the
historical log under each perturbation, refits the agent on that history, and
re-runs all three arms.

Why this is the sweep that matters
----------------------------------
Increasing batch size narrows the confidence interval on a simulated delta. It
does nothing whatever about that delta being computed inside a world whose base
rates were assumed. That is assumption error, it is the largest single threat
to this project's headline number, and no amount of n addresses it.

So the question here is not "is the estimate precise" but "is the finding an
artefact of my specific base rates". If the agent/naive verdict and the
efficiency ratio hold across a wide sweep of both parameters, the finding is
structural. If they flip inside a plausible range, it is not, and that has to
be said plainly.

Note the agent REFITS under each perturbation. This is deliberate: the question
is whether the conclusion holds in a different world, not whether a model fitted
on the wrong world degrades -- which it obviously would, and which would be a
much easier and much less interesting question.

Run:  python -m eval.assumption_sweep
"""

from __future__ import annotations

import math
from typing import Any

import data.generator as G
from agent.diagnosis import LLMDiagnoser, diagnose_batch
from agent.uplift import UpliftModel
from eval.harness import Harness, compare_paired

# Odds-scale shift applied to every base natural-recovery rate. 1.0 is the world
# as generated; 0.5 halves the odds of unaided recovery, 2.0 doubles them.
RECOVERY_POINTS = (0.5, 0.75, 1.0, 1.5, 2.0)

# Shrink/stretch of every treatment effect toward or away from "does nothing".
# 0.0 makes every action exactly neutral, 1.0 is the world as generated, 1.5
# makes every action half again as effective as assumed.
TREATMENT_POINTS = (0.0, 0.5, 0.75, 1.0, 1.5)

N_SWEEP = 6000          # smaller than the 12k holdout; ten worlds to build
N_HISTORY_SWEEP = 12000


def _scale_odds(p: float, factor: float) -> float:
    """Multiply the ODDS of p by factor, keeping the result a probability."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    o = (p / (1 - p)) * factor
    return o / (1 + o)


def _build_world(seed: int, base_scale: float, treat_scale: float
                 ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Regenerate cases, truth and history under perturbed assumptions.

    Patches the generator's module-level assumption tables, generates, then
    restores them -- the same approach sweep_budget takes with
    CONTACT_BUDGET_PER_1000.
    """
    orig_base = dict(G.BASE_NATURAL_RECOVERY)
    orig_mult = {k: dict(v) for k, v in G.ODDS_MULTIPLIER.items()}
    try:
        if base_scale != 1.0:
            G.BASE_NATURAL_RECOVERY.update(
                {k: _scale_odds(v, base_scale) for k, v in orig_base.items()})
        if treat_scale != 1.0:
            for cls, actions in orig_mult.items():
                # Pull each multiplier toward 1.0 (no effect) on the log scale,
                # so a scale of 0 makes every action exactly neutral and the
                # direction of every effect is preserved on the way there.
                G.ODDS_MULTIPLIER[cls].update(
                    {a: math.exp(math.log(m) * treat_scale)
                     for a, m in actions.items()})
        cases, truth = G.generate(N_SWEEP, seed)
        history = G.generate_history(N_HISTORY_SWEEP, seed)
        return cases, truth, history
    finally:
        G.BASE_NATURAL_RECOVERY.clear()
        G.BASE_NATURAL_RECOVERY.update(orig_base)
        G.ODDS_MULTIPLIER.clear()
        G.ODDS_MULTIPLIER.update(orig_mult)


def _run_world(cases, truth, history, seed: int) -> dict[str, Any]:
    """Diagnose, refit on the perturbed history, run all three arms."""
    llm = LLMDiagnoser()
    model = UpliftModel().fit(history, diagnose_batch(history, llm))
    diags = diagnose_batch(cases, llm)
    res = Harness(seed=seed, quiet=True, truth=truth).run_paired(
        cases, model, diags)["results"]
    cmp_ = compare_paired(res)
    return {
        "control_net_per_case": round(res["control"].net_per_case, 2),
        "naive_net_per_case": round(res["naive"].net_per_case, 2),
        "agent_net_per_case": round(res["agent"].net_per_case, 2),
        "agent_contacts": res["agent"].contacts,
        "naive_contacts": res["naive"].contacts,
        "agent_vs_control": cmp_["agent_vs_control"]["net_per_case"],
        "agent_vs_naive": cmp_["agent_vs_naive"]["net_per_case"],
        "agent_vs_naive_ci": cmp_["agent_vs_naive"]["ci"],
        "agent_wins": cmp_["agent_vs_naive"]["net_per_case"] > 0,
        "agent_net_per_contact": cmp_["net_incremental_per_contact"]["agent"],
        "naive_net_per_contact": cmp_["net_incremental_per_contact"]["naive"],
    }


def sweep_base_recovery(seed: int, points=RECOVERY_POINTS) -> list[dict[str, Any]]:
    """Vary how often payments come back unaided (A1)."""
    rows = []
    for f in points:
        cases, truth, hist = _build_world(seed, base_scale=f, treat_scale=1.0)
        row = {
            "natural_recovery_odds_scale": f,
            "mean_p_natural": round(
                sum(t["p_natural"] for t in truth.values()) / len(truth), 4),
        }
        row.update(_run_world(cases, truth, hist, seed))
        rows.append(row)
    return rows


def sweep_treatment_strength(seed: int, points=TREATMENT_POINTS
                             ) -> list[dict[str, Any]]:
    """Vary how much interventions actually help (A4)."""
    rows = []
    for f in points:
        cases, truth, hist = _build_world(seed, base_scale=1.0, treat_scale=f)
        rows.append({"treatment_strength_scale": f,
                     **_run_world(cases, truth, hist, seed)})
    return rows


def main() -> None:
    seed = G.read_seed()
    print("=" * 78)
    print("ASSUMPTION-ERROR SWEEP -- perturbing the world, not the agent")
    print(f"{N_SWEEP} cases per world, agent refitted on {N_HISTORY_SWEEP} "
          f"perturbed history records at each point")
    print("=" * 78)

    verdicts = []

    print("\nA1  natural recovery (odds scale; 1.0 = world as generated)")
    print(f"  {'scale':>6} {'mean p_nat':>11} {'control':>9} {'naive':>9} "
          f"{'agent':>9} {'a-vs-n':>9} {'agent/contact':>14} {'verdict':>8}")
    for r in sweep_base_recovery(seed):
        verdicts.append(r["agent_wins"])
        print(f"  {r['natural_recovery_odds_scale']:>6.2f} "
              f"{r['mean_p_natural']:>11.4f} "
              f"{r['control_net_per_case']:>9.2f} {r['naive_net_per_case']:>9.2f} "
              f"{r['agent_net_per_case']:>9.2f} {r['agent_vs_naive']:>9.2f} "
              f"{r['agent_net_per_contact']:>14.2f} "
              f"{'agent' if r['agent_wins'] else 'naive':>8}")

    print("\nA4  treatment strength (0.0 = every action neutral, 1.0 = as generated)")
    print(f"  {'scale':>6} {'control':>9} {'naive':>9} {'agent':>9} "
          f"{'a-vs-n':>9} {'agent/contact':>14} {'naive/contact':>14} {'verdict':>8}")
    for r in sweep_treatment_strength(seed):
        verdicts.append(r["agent_wins"])
        print(f"  {r['treatment_strength_scale']:>6.2f} "
              f"{r['control_net_per_case']:>9.2f} {r['naive_net_per_case']:>9.2f} "
              f"{r['agent_net_per_case']:>9.2f} {r['agent_vs_naive']:>9.2f} "
              f"{r['agent_net_per_contact']:>14.2f} "
              f"{r['naive_net_per_contact']:>14.2f} "
              f"{'agent' if r['agent_wins'] else 'naive':>8}")

    print("\n" + "-" * 78)
    print(f"agent beats naive on net value in {sum(verdicts)} of {len(verdicts)} "
          f"perturbed worlds")
    print("-" * 78)


if __name__ == "__main__":
    main()
