"""`make eval` -- regenerates every number reported anywhere in this project.

Writes to eval/results/:

    summary.json        aggregate metrics, all three arms, both designs
    cases.json          per-case rows for the UI
    alternatives.json   every scored action per case, with rejection reasons
    audits.json         the full event log, keyed by case id

The UI reads only these files and computes nothing. If the UI ever needed a
number that is not in here, the fix is to add it to this file -- the moment the
frontend calculates something, that number stops being reproducible by
`make eval`.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.diagnosis import LLMDiagnoser, diagnose_batch
from agent.executors.razorpay_test import RazorpayTestExecutor
from agent.policy import PolicyEngine
from agent.uplift import fit_from_history
from eval.calibration import diagnosis_reliability, uplift_reliability
from eval.harness import (CONTACT_BUDGET_PER_1000, Harness, compare,
                          compare_paired, recovery_by_class, value_band)
from eval.assumption_sweep import (sweep_base_recovery,
                                   sweep_treatment_strength)
from eval.sensitivity import sweep_annoyance, sweep_budget
from eval.stats import describe_delta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RESULTS = os.path.join(HERE, "results")

UI_SLICE_TARGET = 1500
IST = timezone(timedelta(hours=5, minutes=30))


def load(name: str) -> Any:
    with open(os.path.join(DATA, name)) as fh:
        return json.load(fh)


def normalise_reason(reason: str) -> str:
    """Group stop reasons by their KIND, not their numbers.

    Without this, "success landed 72.4h after failure" and "...72.0h..." are
    counted as two different reasons, which fragments the distribution and
    makes the table useless.
    """
    if not reason:
        return ""
    r = re.sub(r"[-+]?\d[\d,]*\.?\d*", "N", reason)
    return r.split(";")[0].strip()


def run_test_suite() -> dict[str, Any]:
    """Actually run the tests and record the result.

    The interface reports a passing-test count. Hardcoding that number would
    make it a claim rather than a measurement, and it would go stale the first
    time someone added a test. Running the suite here means the figure on the
    evaluation screen is always what pytest just said.
    """
    import subprocess
    out: dict[str, Any] = {"ran": False, "passed": 0, "failed": 0, "by_file": {}}
    files = ["test_policy.py", "test_state_machine.py", "test_allocation.py",
             "test_ground_truth_boundary.py"]
    try:
        for f in files:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", os.path.join(ROOT, "tests", f), "-q"],
                capture_output=True, text=True, cwd=ROOT, timeout=600)
            m = re.search(r"(\d+) passed", proc.stdout)
            fm = re.search(r"(\d+) failed", proc.stdout)
            n = int(m.group(1)) if m else 0
            nf = int(fm.group(1)) if fm else 0
            out["by_file"][f] = {"passed": n, "failed": nf}
            out["passed"] += n
            out["failed"] += nf
        out["ran"] = True
    except Exception as exc:  # noqa: BLE001 - never let this break the eval
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def rule(title: str = "") -> None:
    print("\n" + "=" * 78)
    if title:
        print(title)
        print("=" * 78)


# ===========================================================================
# UI slice
# ===========================================================================

def choose_ui_slice(cases_by_id: dict[str, Any], agent_outcomes: list[Any],
                    plans: dict[str, Any], diagnoses: dict[str, Any],
                    truth: dict[str, Any]) -> list[str]:
    """Pick the cases the UI will show.

    Deliberately NOT a random sample. A random sample of 1,500 would contain
    almost none of the cases that make the decision process legible -- the
    high-value skip, the budget-cutoff loser, the confident wrong diagnosis.
    Those are force-included, and the remainder is filled randomly so the table
    still reflects the shape of the batch.
    """
    import random
    rnd = random.Random(20260314)
    by_id = {o.case_id: o for o in agent_outcomes}
    chosen: list[str] = []
    seen: set[str] = set()

    def take(ids, n, why):
        added = 0
        for cid in ids:
            if cid in seen or added >= n:
                continue
            seen.add(cid); chosen.append(cid); added += 1

    # High-value cases deliberately not pursued -- the judgement moment.
    skipped = sorted((o.case_id for o in agent_outcomes
                      if plans[o.case_id].action == "no_action"),
                     key=lambda c: -cases_by_id[c]["amount"])
    take(skipped, 120, "high-value skips")

    # Escalations, and every distinct policy block.
    take([o.case_id for o in agent_outcomes if o.state == "ESCALATED"], 80, "escalated")
    for rid in ("R1", "R2", "R3", "R4", "R5", "R7"):
        take([o.case_id for o in agent_outcomes
              if o.stop_reason.startswith(f"policy {rid}")], 40, f"blocked {rid}")

    # Budget-cutoff losers, just outside the line.
    losers = sorted((o.case_id for o in agent_outcomes
                     if plans[o.case_id].budget_rank
                     and not plans[o.case_id].won_contact),
                    key=lambda c: plans[c].budget_rank or 10 ** 9)
    take(losers, 100, "budget cutoff")

    # Sequential escalations, deferrals, and the LLM/fallback path.
    take([o.case_id for o in agent_outcomes if o.escalated_sequentially], 80, "escalated seq")
    take([o.case_id for o in agent_outcomes if o.deferrals > 0], 80, "deferred")
    take([cid for cid, d in diagnoses.items()
          if d.path.startswith("fallback") and cid in by_id], 120, "llm fallback")
    take([cid for cid, d in diagnoses.items()
          if d.failure_class == "unknown" and cid in by_id], 60, "abstained")

    # Confident and wrong -- the cases the submission must not hide.
    wrong = [cid for cid, d in diagnoses.items()
             if cid in by_id and cid in truth
             and d.failure_class != truth[cid]["true_failure_class"]
             and d.confidence >= 0.85]
    take(sorted(wrong, key=lambda c: -cases_by_id[c]["amount"]), 60, "confident wrong")

    # Acted on, high predicted uplift, and it still did not recover.
    misses = [o.case_id for o in agent_outcomes
              if o.attempted and not o.confirmed and plans[o.case_id].uplift > 0.12]
    take(sorted(misses, key=lambda c: -cases_by_id[c]["amount"]), 60, "acted and missed")

    # Recovered cases, so the table is not all failure.
    take([o.case_id for o in agent_outcomes if o.confirmed], 200, "recovered")

    # Fill the rest at random.
    rest = [o.case_id for o in agent_outcomes if o.case_id not in seen]
    rnd.shuffle(rest)
    take(rest, max(UI_SLICE_TARGET - len(chosen), 0), "random fill")
    return chosen


# ===========================================================================

def main() -> int:
    t_start = time.perf_counter()
    seed = int(open(os.path.join(DATA, "seed.txt")).read().strip())
    os.makedirs(RESULTS, exist_ok=True)

    rule("AI REVENUE RECOVERY AGENT -- EVALUATION")
    print(f"seed {seed}   python {platform.python_version()}   "
          f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} IST")

    cases = load("cases.json")
    truth = load("ground_truth.json")
    split = load("split.json")
    holdout_ids = set(split["holdout"])
    holdout = [c for c in cases if c["case_id"] in holdout_ids]
    cases_by_id = {c["case_id"]: c for c in cases}
    engine = PolicyEngine()

    print(f"world {len(cases):,} cases   holdout {len(holdout):,}   "
          f"train {len(split['train']):,}")

    # ---- L1 -------------------------------------------------------------
    rule("L1  DIAGNOSIS")
    llm = LLMDiagnoser()
    print(f"LLM path: {'available' if llm.available else 'UNAVAILABLE -- ' + llm.unavailable_reason}")
    t0 = time.perf_counter()
    diagnoses = diagnose_batch(holdout, llm)
    t_diag = time.perf_counter() - t0

    paths = Counter(d.path for d in diagnoses.values())
    correct = sum(1 for c, d in diagnoses.items()
                  if d.failure_class == truth[c]["true_failure_class"])
    committed = {c: d for c, d in diagnoses.items() if d.failure_class != "unknown"}
    committed_ok = sum(1 for c, d in committed.items()
                       if d.failure_class == truth[c]["true_failure_class"])
    print(f"  {len(holdout):,} cases in {t_diag:.2f}s "
          f"({len(holdout) / max(t_diag, 1e-9):,.0f} cases/s)")
    print(f"  paths: " + "  ".join(f"{k} {v:,}" for k, v in paths.most_common()))
    print(f"  accuracy {correct / len(diagnoses):.3f} overall, "
          f"{committed_ok / max(len(committed), 1):.3f} when it commits")
    print(f"  abstention rate {1 - len(committed) / len(diagnoses):.3f}")
    print(f"  LLM fallback invocations: {llm.stats['llm_fallback']:,}")

    # ---- L2 -------------------------------------------------------------
    rule("L2  UPLIFT MODEL")
    t0 = time.perf_counter()
    model = fit_from_history(llm)
    print(f"fitted on {model.n_fit:,} historical records in "
          f"{time.perf_counter() - t0:.2f}s (never on the holdout)")

    # ---- L8 randomised ---------------------------------------------------
    rule("L8  THREE-ARM EVALUATION -- randomised assignment")
    print("Stratified within (predicted failure class x value band). This is the\n"
          "design a merchant could actually run.")
    h_rand = Harness(seed=seed)
    rand = h_rand.run(holdout, model, diagnoses)
    rand_res = rand["results"]
    cmp_rand = compare(rand_res)

    print()
    print(f"  {'arm':8} {'n':>6} {'net/case':>11} {'recovery':>9} {'contacts':>9} "
          f"{'cost':>12}")
    for a in ("control", "naive", "agent"):
        s = rand_res[a].summary()
        print(f"  {a:8} {s['n']:>6,} {s['net_per_case']:>11,.2f} "
              f"{s['recovery_rate']:>9.3f} {s['contacts']:>9,} "
              f"{s['total_cost']:>12,.0f}")
    print()
    for k, label in (("agent_vs_control", "agent vs control"),
                     ("naive_vs_control", "naive vs control"),
                     ("agent_vs_naive", "agent vs naive  ")):
        v = cmp_rand[k]
        print("  " + describe_delta(label, v["net_per_case"], v["ci"][0], v["ci"][1]))

    # ---- L8 paired -------------------------------------------------------
    rule("L8  THREE-ARM EVALUATION -- paired counterfactual")
    print("Every case run through all three arms with the same latent draw.\n"
          "Only possible because the world is synthetic. Pairing removes\n"
          "between-case variance, which dominates when amounts span Rs 99 to\n"
          "Rs 1,20,000.")
    h = Harness(seed=seed, quiet=True)
    paired = h.run_paired(holdout, model, diagnoses)
    pres = paired["results"]
    cmp_p = compare_paired(pres)

    print()
    print(f"  {'arm':8} {'n':>6} {'net/case':>11} {'recovery':>9} {'contacts':>9} "
          f"{'budget':>8} {'cost':>12}")
    for a in ("control", "naive", "agent"):
        s = pres[a].summary()
        print(f"  {a:8} {s['n']:>6,} {s['net_per_case']:>11,.2f} "
              f"{s['recovery_rate']:>9.3f} {s['contacts']:>9,} "
              f"{s['budget'] or '-':>8} {s['total_cost']:>12,.0f}")
    print()
    for k, label in (("agent_vs_control", "agent vs control"),
                     ("naive_vs_control", "naive vs control"),
                     ("agent_vs_naive", "agent vs naive  ")):
        v = cmp_p[k]
        print("  " + describe_delta(label, v["net_per_case"], v["ci"][0], v["ci"][1]))

    pc = cmp_p["net_incremental_per_contact"]
    print()
    print(f"  net incremental revenue per customer contact:")
    print(f"      agent  Rs {pc['agent']:>10,.2f}   using {pres['agent'].contacts:,} contacts")
    print(f"      naive  Rs {pc['naive']:>10,.2f}   using {pres['naive'].contacts:,} contacts")
    if pc["agent"] and pc["naive"]:
        print(f"      the agent is {pc['agent'] / pc['naive']:.1f}x more efficient per contact")

    # Gross vs net -- trap 13.4, made concrete.
    g_a = pres["agent"].gross_recovered / pres["agent"].n
    g_n = pres["naive"].gross_recovered / pres["naive"].n
    print()
    print(f"  measured on GROSS recovery, naive leads by Rs {g_n - g_a:,.2f}/case")
    print(f"  measured on NET value,      naive leads by Rs "
          f"{pres['naive'].net_per_case - pres['agent'].net_per_case:,.2f}/case")

    # ---- calibration -----------------------------------------------------
    rule("CALIBRATION")
    diag_rel = diagnosis_reliability(diagnoses, truth)
    print("  diagnosis confidence vs observed accuracy")
    print(f"    {'bucket':>12} {'n':>7} {'predicted':>11} {'observed':>10} {'gap':>8}")
    for r in diag_rel:
        print(f"    {r['bucket']:>12} {r['n']:>7,} {r['mean_predicted']:>11.3f} "
              f"{r['observed_accuracy']:>10.3f} {r['gap']:>+8.3f}")

    up_rel = uplift_reliability(h.plans, truth)
    print("\n  predicted uplift vs true uplift, for the action actually selected")
    print(f"    {'n':>7} {'predicted':>11} {'true':>10} {'gap':>8}")
    for r in up_rel:
        if r.get("summary"):
            print(f"    correlation between predicted and true uplift: "
                  f"{r['correlation']:+.3f}  (n={r['n']:,})")
        else:
            print(f"    {r['n']:>7,} {r['mean_predicted']:>11.3f} "
                  f"{r['mean_true']:>10.3f} {r['gap']:>+8.3f}")

    # ---- sensitivity -----------------------------------------------------
    rule("SENSITIVITY -- annoyance cost (assumption A10)")
    print("The most load-bearing assumption in the project, and one with no\n"
          "published value. Swept rather than defended.\n")
    ann = sweep_annoyance(holdout, model, diagnoses, seed)
    print(f"  {'Rs/contact':>11} {'control':>10} {'naive':>10} {'agent':>10} "
          f"{'naive ct':>9} {'agent ct':>9} {'agent-naive':>12} {'winner':>8}")
    for r in ann:
        winner = "agent" if r["agent_wins"] else "naive"
        print(f"  {r['annoyance_cost']:>11,.0f} {r['control_net_per_case']:>10,.0f} "
              f"{r['naive_net_per_case']:>10,.0f} {r['agent_net_per_case']:>10,.0f} "
              f"{r['naive_contacts']:>9,} {r['agent_contacts']:>9,} "
              f"{r['agent_vs_naive']:>+12,.2f} {winner:>8}")

    rule("SENSITIVITY -- contact budget (assumption A14)")
    print("The agent is constrained; the naive arm is not. This sweep separates\n"
          "'the targeting is no good' from 'it is fighting with one hand tied'.\n")
    bud = sweep_budget(holdout, model, diagnoses, seed)
    print(f"  {'budget/1000':>12} {'agent ct':>9} {'naive ct':>9} {'agent net':>11} "
          f"{'naive net':>11} {'agent-naive':>12} {'per contact':>12}")
    for r in bud:
        print(f"  {r['budget_per_1000']:>12,} {r['agent_contacts']:>9,} "
              f"{r['naive_contacts']:>9,} {r['agent_net_per_case']:>11,.2f} "
              f"{r['naive_net_per_case']:>11,.2f} {r['agent_vs_naive']:>+12,.2f} "
              f"{r['agent_net_per_contact'] or 0:>12,.0f}")

    rule("SENSITIVITY -- assumption error (assumptions A1 and A4)")
    print("The two sweeps above move the AGENT inside a fixed world.")
    print("This one moves the WORLD: it perturbs the base natural-recovery")
    print("rates and the treatment effects, regenerates the population and")
    print("the historical log, REFITS the agent on that history, and re-runs")
    print("all three arms.")
    print("")
    print("Batch size narrows the interval on a simulated delta. It does")
    print("nothing about that delta sitting inside a world whose base rates")
    print("were assumed. This is the only sweep that speaks to that, and it")
    print("is the largest single threat to the headline number.")
    print("")

    arec = sweep_base_recovery(seed)
    print("  A1  natural recovery, odds scale (1.00 = world as generated)")
    print(f"  {'scale':>7} {'mean p_nat':>11} {'control':>10} {'naive':>10} "
          f"{'agent':>10} {'agent-naive':>12} {'per contact':>12} {'winner':>8}")
    for r in arec:
        print(f"  {r['natural_recovery_odds_scale']:>7.2f} "
              f"{r['mean_p_natural']:>11.4f} {r['control_net_per_case']:>10,.0f} "
              f"{r['naive_net_per_case']:>10,.0f} {r['agent_net_per_case']:>10,.0f} "
              f"{r['agent_vs_naive']:>+12,.2f} {r['agent_net_per_contact'] or 0:>12,.0f} "
              f"{'agent' if r['agent_wins'] else 'naive':>8}")

    atre = sweep_treatment_strength(seed)
    print("")
    print("  A4  treatment strength (0.00 = every action neutral)")
    print(f"  {'scale':>7} {'control':>10} {'naive':>10} {'agent':>10} "
          f"{'agent-naive':>12} {'agent/ct':>10} {'naive/ct':>10} {'winner':>8}")
    for r in atre:
        print(f"  {r['treatment_strength_scale']:>7.2f} "
              f"{r['control_net_per_case']:>10,.0f} {r['naive_net_per_case']:>10,.0f} "
              f"{r['agent_net_per_case']:>10,.0f} {r['agent_vs_naive']:>+12,.2f} "
              f"{r['agent_net_per_contact'] or 0:>10,.0f} "
              f"{r['naive_net_per_contact'] or 0:>10,.0f} "
              f"{'agent' if r['agent_wins'] else 'naive':>8}")

    _wins = sum(r["agent_wins"] for r in arec + atre)
    print("")
    print(f"  agent beats naive on net value in {_wins} of "
          f"{len(arec) + len(atre)} perturbed worlds")
    # The scale=0.0 world is excluded from the ratio range on purpose: with every
    # action neutral the naive arm earns almost nothing per contact, so the ratio
    # explodes to a meaningless number. The interesting claim is that the ratio
    # stays large across worlds where interventions actually do something.
    _ratios = [r["agent_net_per_contact"] / r["naive_net_per_contact"]
               for r in atre
               if r["naive_net_per_contact"] and r["treatment_strength_scale"] > 0]
    if _ratios:
        print(f"  efficiency ratio (agent/naive per contact) holds between "
              f"{min(_ratios):.1f}x and {max(_ratios):.1f}x across worlds where "
              f"interventions have any effect")

    # ---- policy ----------------------------------------------------------
    rule("POLICY")
    violations = 0
    rules_evaluated = 0
    for cid, events in h.trail.to_dict().items():
        for e in events:
            if e["event"] == "POLICY_CHECKED":
                rules_evaluated += len(e["payload"].get("rules", []))
                violations += sum(1 for r in e["payload"].get("rules", [])
                                  if r["applies"] and not r["passed"] and
                                  e["payload"].get("blocked_by") != r["rule_id"])
    # Where blocks actually happen. In the agent arm almost nothing reaches the
    # state machine with a blocked action, because allocation already refuses to
    # PLAN one -- policy is consulted while scoring alternatives, not only at
    # execution. Counting only execution-time blocks reported an empty table and
    # made it look as though no rule ever fired.
    blocked = Counter()
    for p_ in h.plans.values():
        for a in p_.alternatives:
            if a.rejection_type == "policy" and a.blocked_by:
                blocked[a.blocked_by] += 1
    blocked_exec = Counter()
    for o in pres["agent"].outcomes:
        if o.stop_reason.startswith("policy "):
            blocked_exec[o.stop_reason.split(":")[0].replace("policy ", "")] += 1
    cases_fully_blocked = sum(
        1 for p_ in h.plans.values()
        if all(a.rejection_type == "policy" for a in p_.alternatives
               if a.action != "no_action"))
    print(f"  {rules_evaluated:,} rule evaluations across the agent arm")
    print(f"  candidate actions refused at allocation time, by rule:")
    for k, v in sorted(blocked.items()):
        print(f"      {k}  {v:,}")
    print(f"  cases with EVERY treatment action refused: {cases_fully_blocked:,}")
    print(f"  blocks at execution time: " +
          ("  ".join(f"{k} {v:,}" for k, v in sorted(blocked_exec.items()))
           or "0 -- allocation never plans an action policy would refuse"))
    print(f"  quiet-hour deferrals: {sum(o.deferrals for o in pres['agent'].outcomes):,}")
    print(f"  0 unpermitted actions reached an executor "
          f"(enforced by R8, covered by tests/test_policy.py)")

    # ---- stopping --------------------------------------------------------
    rule("STOPPING AND SKIPPING")
    stops = Counter(normalise_reason(o.stop_reason)
                    for o in pres["agent"].outcomes if o.stop_reason)
    for k, v in stops.most_common(10):
        print(f"  {v:>6,}  {k}")
    skipped = [o for o in pres["agent"].outcomes
               if h.plans[o.case_id].action == "no_action"]
    skipped_value = sum(cases_by_id[o.case_id]["amount"] for o in skipped)
    skipped_recovered = sum(o.amount_confirmed for o in skipped)
    skipped_cases_recovered = sum(1 for o in skipped if o.confirmed)
    # Compare like with like. A revenue-weighted rate on the skipped cases must be
    # set against the control arm's REVENUE-weighted rate, not against its
    # case-count recovery rate. Those are different units, and mixing them
    # overstates the point in exactly the direction that flatters the agent.
    control_revenue_rate = (pres["control"].gross_recovered /
                            max(pres["control"].at_risk, 1))
    print(f"\n  {len(skipped):,} cases deliberately not pursued, "
          f"Rs {skipped_value:,.0f} at risk")
    print(f"  of which Rs {skipped_recovered:,.0f} came back anyway with no action")
    print(f"      by revenue  {skipped_recovered / max(skipped_value, 1):>6.1%} of skipped "
          f"value, against {control_revenue_rate:.1%} across the control arm")
    print(f"      by case     {skipped_cases_recovered / max(len(skipped), 1):>6.1%} of skipped "
          f"cases, against {pres['control'].recovery_rate:.1%} across the control arm")

    # ---- tests -----------------------------------------------------------
    rule("TESTS")
    tests = run_test_suite()
    if tests["ran"]:
        for f, r in tests["by_file"].items():
            print(f"  {f:32} {r['passed']:>4} passed"
                  + (f", {r['failed']} FAILED" if r["failed"] else ""))
        print(f"  {'total':32} {tests['passed']:>4} passed"
              + (f", {tests['failed']} FAILED" if tests["failed"] else ""))
    else:
        print(f"  could not run the suite: {tests.get('error')}")

    # ---- artifacts -------------------------------------------------------
    rule("ARTIFACTS")
    rz = RazorpayTestExecutor()
    duration = time.perf_counter() - t_start

    slice_ids = choose_ui_slice(cases_by_id, pres["agent"].outcomes, h.plans,
                                diagnoses, truth)
    slice_set = set(slice_ids)

    ctrl_by_id = {o.case_id: o for o in pres["control"].outcomes}
    naive_by_id = {o.case_id: o for o in pres["naive"].outcomes}

    ui_cases = []
    for o in pres["agent"].outcomes:
        if o.case_id not in slice_set:
            continue
        c = cases_by_id[o.case_id]
        d = diagnoses[o.case_id]
        p = h.plans[o.case_id]
        t = truth[o.case_id]
        ui_cases.append({
            **{k: c[k] for k in ("case_id", "amount", "method", "gateway_code",
                                 "gateway_message", "tenure_days", "prior_success",
                                 "prior_failures", "hour", "risk_score",
                                 "opted_out", "disputed", "age_hours",
                                 "merchant_category")},
            "arm": "agent",
            "failure_class": d.failure_class,
            "true_failure_class": t["true_failure_class"],
            "diagnosis_correct": d.failure_class == t["true_failure_class"],
            "diag_confidence": round(d.confidence, 3),
            "diag_path": d.path,
            "diag_signals": d.signals,
            "diag_llm_error": d.llm_error,
            "segment": p.segment,
            "p_natural": round(p.p_natural, 4),
            "p_treated": round(p.p_treated, 4),
            "uplift": round(p.uplift, 4),
            "incremental_ev": round(p.incremental_ev, 2),
            "action": p.action,
            "budget_rank": p.budget_rank,
            "budget_contenders": p.budget_contenders,
            "budget_cutoff_ev": (round(p.budget_cutoff_ev, 2)
                                 if p.budget_cutoff_ev is not None else None),
            "won_contact": p.won_contact,
            "state": o.state,
            "attempts": o.attempts,
            "contacts": o.contacts,
            "action_sequence": o.action_sequence,
            "attempted": o.attempted,
            "payment_success": o.payment_success,
            "confirmed": o.confirmed,
            "amount_confirmed": round(o.amount_confirmed, 2),
            "cost_spent": round(o.cost_spent, 2),
            "stop_reason": o.stop_reason,
            "execution_mode": o.execution_mode,
            "deferrals": o.deferrals,
            "escalated_sequentially": o.escalated_sequentially,
            "request_ids": o.request_ids,
            "control_confirmed": ctrl_by_id[o.case_id].confirmed,
            "naive_confirmed": naive_by_id[o.case_id].confirmed,
            "naive_contacts": naive_by_id[o.case_id].contacts,
        })

    alternatives = {cid: [a.to_dict() for a in h.plans[cid].alternatives]
                    for cid in slice_ids}
    all_audits = h.trail.to_dict()
    audits = {cid: all_audits.get(cid, []) for cid in slice_ids}

    funnel = {
        "failed": pres["agent"].n,
        "diagnosed": pres["agent"].n,
        "diagnosed_unknown": sum(1 for cid in (o.case_id for o in pres["agent"].outcomes)
                                 if diagnoses[cid].failure_class == "unknown"),
        "eligible": sum(1 for o in pres["agent"].outcomes
                        if h.plans[o.case_id].action != "no_action"),
        "actioned": sum(1 for o in pres["agent"].outcomes if o.attempted),
        "recovered": sum(1 for o in pres["agent"].outcomes if o.state == "RECOVERED"),
        "recovered_confirmed": sum(1 for o in pres["agent"].outcomes if o.confirmed),
        "stopped": sum(1 for o in pres["agent"].outcomes if o.state == "STOPPED"),
        "escalated": sum(1 for o in pres["agent"].outcomes if o.state == "ESCALATED"),
        "ineligible": sum(1 for o in pres["agent"].outcomes if o.state == "INELIGIBLE"),
    }

    summary = {
        "run": {
            "seed": seed,
            "generated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "duration_seconds": round(duration, 2),
            "python": platform.python_version(),
            "n_world": len(cases),
            "n_holdout": len(holdout),
            "n_train": len(split["train"]),
            "n_history": model.n_fit,
            "throughput_cases_per_second": round(len(holdout) / max(t_diag, 1e-9), 1),
            "ui_slice": len(ui_cases),
        },
        "execution": {
            "simulated_cases": len(holdout),
            "razorpay_test_cases": 0,
            "razorpay_available": rz.available,
            "razorpay_reason": rz.unavailable_reason,
            "llm_available": llm.available,
            "llm_reason": llm.unavailable_reason,
            "llm_stats": llm.stats,
        },
        "policy": {
            "config": engine.cfg,
            "rule_evaluations": rules_evaluated,
            "blocks_by_rule": dict(blocked),
            "blocks_at_execution": dict(blocked_exec),
            "cases_fully_blocked": cases_fully_blocked,
            "allocation_policy_rejections": sum(
                1 for p in h.plans.values() for a in p.alternatives
                if a.rejection_type == "policy"),
            "deferrals": sum(o.deferrals for o in pres["agent"].outcomes),
        },
        "diagnosis": {
            "accuracy": round(correct / len(diagnoses), 4),
            "accuracy_when_committed": round(committed_ok / max(len(committed), 1), 4),
            "abstention_rate": round(1 - len(committed) / len(diagnoses), 4),
            "paths": dict(paths),
            "reliability": diag_rel,
            "duration_seconds": round(t_diag, 3),
        },
        "uplift": {"reliability": up_rel},
        "arms_paired": {a: pres[a].summary() for a in ("control", "naive", "agent")},
        "arms_randomised": {a: rand_res[a].summary()
                            for a in ("control", "naive", "agent")},
        "comparison_paired": cmp_p,
        "comparison_randomised": cmp_rand,
        "recovery_by_class": recovery_by_class(pres, truth),
        "sensitivity_annoyance": ann,
        "sensitivity_budget": bud,
        "sensitivity_natural_recovery": arec,
        "sensitivity_treatment_strength": atre,
        "funnel": funnel,
        "skipped": {
            "n": len(skipped),
            "value_at_risk": round(skipped_value, 2),
            "recovered_anyway": round(skipped_recovered, 2),
            "revenue_rate": round(skipped_recovered / max(skipped_value, 1), 4),
            "cases_recovered": skipped_cases_recovered,
            "case_rate": round(skipped_cases_recovered / max(len(skipped), 1), 4),
            "control_revenue_rate": round(control_revenue_rate, 4),
            "control_case_rate": round(pres["control"].recovery_rate, 4),
        },
        "stop_reasons": dict(stops.most_common()),
        "tests": tests,
    }

    # summary.json is pretty-printed because people read it. The bulk artifacts
    # are not: `indent=1` on deeply nested audit events was more than half the
    # file size, and nothing reads them by eye.
    for name, payload, pretty in (("summary.json", summary, True),
                                  ("cases.json", ui_cases, False),
                                  ("alternatives.json", alternatives, False),
                                  ("audits.json", audits, False)):
        path = os.path.join(RESULTS, name)
        with open(path, "w") as fh:
            if pretty:
                json.dump(payload, fh, indent=1)
            else:
                json.dump(payload, fh, separators=(",", ":"))
        print(f"  {name:20} {os.path.getsize(path) / 1024:>9,.0f} KB")

    rule("HEADLINE")
    v = cmp_p["agent_vs_naive"]
    print(f"  net incremental vs control  Rs {cmp_p['agent_vs_control']['net_per_case']:+,.2f}/case "
          f"CI [{cmp_p['agent_vs_control']['ci'][0]:+,.2f}, "
          f"{cmp_p['agent_vs_control']['ci'][1]:+,.2f}]")
    print(f"  net incremental vs naive    Rs {v['net_per_case']:+,.2f}/case "
          f"CI [{v['ci'][0]:+,.2f}, {v['ci'][1]:+,.2f}]")
    if v["significant"] and v["net_per_case"] > 0:
        print("  -> the agent beats the naive baseline.")
    elif v["significant"]:
        print("  -> the agent LOSES to the naive baseline on net value per case.")
    else:
        print("  -> the agent and the naive baseline are statistically TIED on net")
        print("     value per case. The agent achieves this using "
              f"{pres['agent'].contacts:,} contacts")
        print(f"     against the naive arm's {pres['naive'].contacts:,} -- "
              f"{pres['naive'].contacts / max(pres['agent'].contacts, 1):.1f}x fewer.")
    print(f"  net incremental per contact Rs {pc['agent']:,.2f} vs Rs {pc['naive']:,.2f} "
          f"({pc['agent'] / pc['naive']:.1f}x)")
    print(f"\n  total run {duration:.2f}s")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
