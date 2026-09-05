"""Diagnostic error analysis -- where the diagnosis layer actually goes wrong.

Overall accuracy is one number and it hides everything worth knowing. A layer
that is 76% accurate could be uniformly mediocre, or excellent on the four large
classes and useless on the two small ones, and those call for entirely different
work. This module answers that.

It reports, on the holdout only:

  * a confusion matrix over true x predicted class
  * per-class precision, recall, F1 and support
  * accuracy by diagnosis path, payment method, and gateway code
  * the confusion PAIRS that carry the most error, ranked
  * error attribution -- what share of total error each slice contributes

The last one is the point. Ranking slices by their own accuracy tells you where
the agent is worst; ranking by contribution to total error tells you where the
work is. They are rarely the same list, and optimising the first is how people
spend a week improving a slice worth 0.3 points.

This module lives in eval/ because it reads ground truth. It is a scorer, never
a decision input, and nothing in agent/ may import it.

Run:  python -m eval.diagnostics
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Any

from agent.constants import DIAGNOSIS_OUTPUTS, FAILURE_CLASSES

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")


# --------------------------------------------------------------------- metrics

def confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """true class -> predicted class -> count."""
    m: dict[str, dict[str, int]] = {
        t: {p: 0 for p in DIAGNOSIS_OUTPUTS} for t in FAILURE_CLASSES}
    for r in rows:
        m[r["true"]][r["pred"]] += 1
    return m


def per_class_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Precision, recall, F1 and support for every class.

    `unknown` gets precision but no recall -- it is never a true class, so there
    is nothing to recall. Reporting a recall of 0.0 for it would look like a
    failure when it is a category error.
    """
    out = []
    for cls in DIAGNOSIS_OUTPUTS:
        tp = sum(1 for r in rows if r["pred"] == cls and r["true"] == cls)
        fp = sum(1 for r in rows if r["pred"] == cls and r["true"] != cls)
        fn = sum(1 for r in rows if r["pred"] != cls and r["true"] == cls)
        support = sum(1 for r in rows if r["true"] == cls)
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if support else None
        f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else None
        out.append({
            "class": cls,
            "support": support,
            "predicted": tp + fp,
            "precision": round(prec, 4) if prec is not None else None,
            "recall": round(rec, 4) if rec is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
        })
    return out


def _slice_table(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Accuracy and error CONTRIBUTION for every value of one field."""
    total_errors = sum(1 for r in rows if not r["correct"]) or 1
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        a = agg[str(r[key])]
        a[0] += r["correct"]
        a[1] += 1
    out = []
    for value, (hits, n) in agg.items():
        errors = n - hits
        out.append({
            key: value,
            "n": n,
            "accuracy": round(hits / n, 4),
            "errors": errors,
            "share_of_all_errors": round(errors / total_errors, 4),
        })
    return sorted(out, key=lambda d: -d["errors"])


def top_confusions(rows: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    c = Counter((r["true"], r["pred"]) for r in rows if not r["correct"])
    total = sum(c.values()) or 1
    return [{"true": t, "predicted": p, "n": k,
             "share_of_all_errors": round(k / total, 4)}
            for (t, p), k in c.most_common(n)]


# ----------------------------------------------------------------------- build

def build_rows(cases: list[dict[str, Any]], truth: dict[str, Any],
               diagnoses: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for c in cases:
        d = diagnoses[c["case_id"]]
        rows.append({
            "case_id": c["case_id"],
            "true": truth[c["case_id"]]["true_failure_class"],
            "pred": d.failure_class,
            "correct": d.failure_class == truth[c["case_id"]]["true_failure_class"],
            "confidence": d.confidence,
            "path": d.path,
            "method": c["method"],
            "gateway_code": c["gateway_code"] or "(none)",
            "prior_failures": c["prior_failures"],
        })
    return rows


def analyse(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    hits = sum(r["correct"] for r in rows)
    committed = [r for r in rows if r["pred"] != "unknown"]
    return {
        "n": n,
        "accuracy": round(hits / n, 4),
        "accuracy_when_committed": round(
            sum(r["correct"] for r in committed) / len(committed), 4),
        "abstention_rate": round(1 - len(committed) / n, 4),
        "confusion_matrix": confusion_matrix(rows),
        "per_class": per_class_metrics(rows),
        "by_path": _slice_table(rows, "path"),
        "by_method": _slice_table(rows, "method"),
        "by_gateway_code": _slice_table(rows, "gateway_code"),
        "top_confusions": top_confusions(rows),
    }


# ------------------------------------------------------------------------ main

def _load_holdout():
    from agent.diagnosis import LLMDiagnoser, diagnose_batch
    with open(os.path.join(DATA, "cases.json")) as fh:
        cases = json.load(fh)
    with open(os.path.join(DATA, "ground_truth.json")) as fh:
        truth = json.load(fh)
    with open(os.path.join(DATA, "split.json")) as fh:
        holdout = set(json.load(fh)["holdout"])
    cases = [c for c in cases if c["case_id"] in holdout]
    return cases, truth, diagnose_batch(cases, LLMDiagnoser())


def print_report(a: dict[str, Any]) -> None:
    bar = "=" * 78
    print(bar)
    print("DIAGNOSTIC ERROR ANALYSIS -- holdout only")
    print(bar)
    print(f"  n {a['n']:,}   accuracy {a['accuracy']:.4f}   "
          f"when committed {a['accuracy_when_committed']:.4f}   "
          f"abstained {a['abstention_rate']:.4f}")

    print(f"\n  Per-class (support = how many truly are this class)")
    print(f"  {'class':<24}{'support':>9}{'predicted':>11}"
          f"{'precision':>11}{'recall':>9}{'f1':>8}")
    for r in a["per_class"]:
        f = lambda v: f"{v:.4f}" if v is not None else "     -"
        print(f"  {r['class']:<24}{r['support']:>9,}{r['predicted']:>11,}"
              f"{f(r['precision']):>11}{f(r['recall']):>9}{f(r['f1']):>8}")

    print(f"\n  Confusion matrix (rows = true, columns = predicted)")
    cols = list(DIAGNOSIS_OUTPUTS)
    print(f"  {'':<24}" + "".join(f"{c[:9]:>10}" for c in cols))
    for t in FAILURE_CLASSES:
        row = a["confusion_matrix"][t]
        print(f"  {t:<24}" + "".join(f"{row[c]:>10,}" for c in cols))

    for label, key in (("diagnosis path", "by_path"),
                       ("payment method", "by_method")):
        print(f"\n  Accuracy by {label} (ranked by share of total error)")
        print(f"  {'value':<26}{'n':>8}{'accuracy':>10}{'errors':>9}{'% of error':>12}")
        for r in a[key]:
            v = r.get("path") or r.get("method")
            print(f"  {v:<26}{r['n']:>8,}{r['accuracy']:>10.4f}"
                  f"{r['errors']:>9,}{r['share_of_all_errors']:>11.1%}")

    print(f"\n  Accuracy by gateway code -- top 8 error contributors")
    print(f"  {'code':<36}{'n':>8}{'accuracy':>10}{'errors':>9}{'% of error':>12}")
    for r in a["by_gateway_code"][:8]:
        print(f"  {r['gateway_code']:<36}{r['n']:>8,}{r['accuracy']:>10.4f}"
              f"{r['errors']:>9,}{r['share_of_all_errors']:>11.1%}")

    print(f"\n  Most costly confusions")
    print(f"  {'true':<24}{'predicted as':<24}{'n':>8}{'% of error':>12}")
    for r in a["top_confusions"]:
        print(f"  {r['true']:<24}{r['predicted']:<24}{r['n']:>8,}"
              f"{r['share_of_all_errors']:>11.1%}")
    print()


def main() -> None:
    cases, truth, diags = _load_holdout()
    print_report(analyse(build_rows(cases, truth, diags)))


if __name__ == "__main__":
    main()


# ------------------------------------------------------- downstream value

def oracle_ablation(cases: list[dict[str, Any]], truth: dict[str, Any],
                    real_diagnoses: dict[str, Any], seed: int) -> dict[str, Any]:
    """What is PERFECT diagnosis actually worth, in money?

    Diagnosis accuracy is an intermediate metric. The project is scored on net
    value, so an accuracy gain only matters if it moves that. This measures the
    ceiling: replace the diagnosis layer with ground truth, refit, re-run all
    three arms, and report the difference.

    The uplift model is REFITTED on an oracle-diagnosed history, not reused.
    Reusing a table keyed on predicted classes while scoring with true ones
    would measure a key mismatch rather than the value of being right.

    Expect the gap to be small. The uplift table is keyed on the PREDICTED
    class, so it already learns the right action for "cases that look like
    insufficient_funds", mislabels included -- the pipeline absorbs a good deal
    of diagnostic error on its own. If that is true, the number to improve is
    not accuracy.

    This reads ground truth and is therefore an EVALUATION-ONLY path. It never
    runs in the agent pipeline and nothing in agent/ may import it.
    """
    from agent.diagnosis import Diagnosis, LLMDiagnoser, diagnose_batch
    from agent.uplift import UpliftModel
    from data.generator import generate_history, read_seed
    from eval.harness import Harness, compare_paired

    def _oracle(cid: str) -> Diagnosis:
        return Diagnosis(truth[cid]["true_failure_class"], 1.0,
                         ["oracle diagnosis (evaluation only)"], "oracle")

    llm = LLMDiagnoser()
    history = generate_history(seed=read_seed())

    real_model = UpliftModel().fit(history, diagnose_batch(history, llm))
    real = Harness(seed=seed, quiet=True).run_paired(
        cases, real_model, real_diagnoses)["results"]

    # The history log is deliberately observable-only, so its true labels have to
    # be recovered from the generator directly. generate_history() draws from
    # generate(n, seed + HISTORY_SEED_OFFSET) and renames REC-n to HIST-n, so the
    # ids line up one for one.
    import data.generator as G
    _, hist_truth = G.generate(len(history), read_seed() + G.HISTORY_SEED_OFFSET)
    hist_truth = {"HIST-" + k.split("-")[1]: v for k, v in hist_truth.items()}
    oracle_hist_diags = {
        h["case_id"]: Diagnosis(hist_truth[h["case_id"]]["true_failure_class"],
                               1.0, ["oracle"], "oracle")
        for h in history if h["case_id"] in hist_truth}
    if len(oracle_hist_diags) != len(history):
        oracle_model = real_model
        fit_note = ("history truth incomplete (%d of %d); uplift table reused"
                    % (len(oracle_hist_diags), len(history)))
    else:
        oracle_model = UpliftModel().fit(history, oracle_hist_diags)
        fit_note = "uplift table refitted on oracle-diagnosed history"

    oracle_diags = {c["case_id"]: _oracle(c["case_id"]) for c in cases}
    oracle = Harness(seed=seed, quiet=True).run_paired(
        cases, oracle_model, oracle_diags)["results"]

    rc, oc = compare_paired(real), compare_paired(oracle)
    return {
        "fit_note": fit_note,
        "real": {
            "agent_net_per_case": round(real["agent"].net_per_case, 2),
            "agent_vs_control": rc["agent_vs_control"]["net_per_case"],
            "agent_vs_naive": rc["agent_vs_naive"]["net_per_case"],
            "agent_contacts": real["agent"].contacts,
            "net_per_contact": rc["net_incremental_per_contact"]["agent"],
        },
        "oracle": {
            "agent_net_per_case": round(oracle["agent"].net_per_case, 2),
            "agent_vs_control": oc["agent_vs_control"]["net_per_case"],
            "agent_vs_naive": oc["agent_vs_naive"]["net_per_case"],
            "agent_contacts": oracle["agent"].contacts,
            "net_per_contact": oc["net_incremental_per_contact"]["agent"],
        },
        "ceiling_net_per_case": round(
            oracle["agent"].net_per_case - real["agent"].net_per_case, 2),
    }
