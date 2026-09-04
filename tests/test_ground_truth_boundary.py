"""The most important test file in the project.

If hidden ground truth leaks into any decision-making layer, the evaluation is
circular and every number in the submission is worthless -- and one question
from a panel collapses it. So the boundary is not a convention here, it is
asserted three ways:

  1. STATIC.  No module under agent/ may name a ground-truth field, except the
     simulator, which is part of L0.
  2. STRUCTURAL.  The ground truth lives in a separate file that the agent
     modules never open.
  3. BEHAVIOURAL.  The agent produces identical decisions when the ground-truth
     file is replaced with garbage -- which it could not do if it were reading
     it.
"""

from __future__ import annotations

import ast
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(ROOT, "agent")

# Names that exist ONLY in the hidden ground truth and have no legitimate
# agent-side analogue.
#
# Note what is deliberately NOT on this list: `p_natural` and `p_treated`. The
# agent has its own estimates of both, fitted from observed outcomes, and they
# are correctly named after the quantities they estimate. Forbidding the words
# would test naming rather than leakage. What cannot be estimated and must never
# be referenced is the TRUE class and the hidden annoyance trait.
FORBIDDEN_NAMES = ("true_failure_class", "annoyance_prone", "ground_truth")

# Importing the generator would hand a decision layer the actual base rates and
# odds multipliers -- a subtler leak than reading the file, and a real one.
FORBIDDEN_IMPORTS = ("data.generator", "generator")


def strip_docstrings(tree: ast.AST) -> None:
    """Discussing the boundary in prose is not crossing it."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body.pop(0)

# The one file inside agent/ that is permitted to touch ground truth, because
# it is the L0 world simulator rather than a decision-making layer.
PERMITTED = {os.path.join(AGENT, "executors", "simulator.py")}


def agent_modules() -> list[str]:
    out = []
    for dirpath, _, files in os.walk(AGENT):
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def decision_modules() -> list[str]:
    return [m for m in agent_modules() if m not in PERMITTED]


# ===========================================================================
# 1. Static
# ===========================================================================

def test_no_decision_module_names_a_ground_truth_field():
    offences = []
    for path in decision_modules():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        strip_docstrings(tree)

        tokens: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                tokens.append(node.attr)
            elif isinstance(node, ast.Name):
                tokens.append(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                tokens.append(node.value)

        for bad in FORBIDDEN_NAMES:
            if any(bad in t for t in tokens):
                offences.append(f"{os.path.relpath(path, ROOT)} references {bad!r}")
    assert not offences, ("ground truth leaked into a decision layer:\n"
                          + "\n".join(offences))


def test_no_decision_module_imports_the_generator():
    """Importing the generator would expose BASE_NATURAL_RECOVERY and
    ODDS_MULTIPLIER -- the actual generative parameters. Reading those is a
    subtler leak than opening the ground-truth file, and just as fatal."""
    offences = []
    for path in decision_modules():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                if any(m == f or m.endswith("." + f) or m.startswith(f + ".")
                       for f in FORBIDDEN_IMPORTS):
                    offences.append(f"{os.path.relpath(path, ROOT)} imports {m}")
    assert not offences, "generator internals reachable from a decision layer:\n" + "\n".join(offences)


def test_no_decision_module_opens_the_ground_truth_file():
    for path in decision_modules():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        assert "ground_truth.json" not in src, (
            f"{os.path.relpath(path, ROOT)} opens the ground-truth file")


def test_simulator_is_the_only_permitted_reader():
    """If this fails, someone added a second reader. That is a design decision,
    not a typo, and it should be made deliberately."""
    readers = []
    for path in agent_modules():
        with open(path, encoding="utf-8") as fh:
            if "ground_truth.json" in fh.read():
                readers.append(path)
    assert set(readers) <= PERMITTED


# ===========================================================================
# 2. Structural
# ===========================================================================

def test_observable_cases_carry_no_ground_truth_fields():
    with open(os.path.join(ROOT, "data", "cases.json")) as fh:
        cases = json.load(fh)
    for case in cases[:200]:
        for bad in FORBIDDEN_NAMES:
            assert bad not in case, f"{case['case_id']} exposes {bad}"


def test_history_log_carries_outcomes_but_no_probabilities():
    """The agent is fitted on this. It must contain observed binary outcomes and
    nothing that reveals the probability behind them."""
    path = os.path.join(ROOT, "data", "history.json")
    if not os.path.exists(path):
        pytest.skip("run `make data` first")
    with open(path) as fh:
        log = json.load(fh)
    for rec in log[:200]:
        assert isinstance(rec["recovered"], bool)
        assert rec["action_taken"]
        for bad in FORBIDDEN_NAMES:
            assert bad not in rec


def test_ground_truth_lives_in_its_own_file():
    with open(os.path.join(ROOT, "data", "ground_truth.json")) as fh:
        truth = json.load(fh)
    any_key = next(iter(truth))
    assert {"p_natural", "p_treated", "true_failure_class"} <= set(truth[any_key])


# ===========================================================================
# 3. Behavioural -- the check that cannot be fooled by clever naming
# ===========================================================================

def test_agent_decisions_are_unchanged_when_ground_truth_is_corrupted(tmp_path):
    """Score and plan a batch twice: once normally, once with every ground-truth
    value replaced by nonsense. If any decision changes, something is reading it.
    """
    from agent.diagnosis import LLMDiagnoser, diagnose_batch
    from agent.policy import PolicyEngine
    from agent.uplift import UpliftModel
    from agent.valuation import Allocator

    with open(os.path.join(ROOT, "data", "cases.json")) as fh:
        cases = json.load(fh)[:400]
    with open(os.path.join(ROOT, "data", "history.json")) as fh:
        history = json.load(fh)[:4000]

    llm = LLMDiagnoser(use_cache=False)
    diags = diagnose_batch(cases, llm)
    hist_diags = diagnose_batch(history, llm)
    model = UpliftModel().fit(history, hist_diags)
    alloc = Allocator(PolicyEngine())

    def plan_all():
        scores = {c["case_id"]: model.score(c, diags[c["case_id"]].failure_class)
                  for c in cases}
        plans = alloc.plan_batch(cases, scores, budget=60)
        return {cid: (p.action, round(p.incremental_ev, 6), round(p.uplift, 6))
                for cid, p in plans.items()}

    before = plan_all()

    # Corrupt the on-disk ground truth. Nothing in the decision path should
    # notice, because nothing in the decision path reads it.
    gt_path = os.path.join(ROOT, "data", "ground_truth.json")
    with open(gt_path) as fh:
        original = fh.read()
    try:
        corrupted = {k: {"p_natural": 0.999, "p_treated": {},
                         "true_failure_class": "nonsense",
                         "annoyance_prone": True}
                     for k in json.loads(original)}
        with open(gt_path, "w") as fh:
            json.dump(corrupted, fh)
        after = plan_all()
    finally:
        with open(gt_path, "w") as fh:
            fh.write(original)

    assert before == after, "agent decisions changed when ground truth changed"


def test_agent_p_natural_estimate_differs_from_the_true_one():
    """A sanity check on the other side: if the agent's estimate matched ground
    truth exactly, that would itself be evidence of leakage. It should be
    correlated but clearly imperfect."""
    import numpy as np
    from agent.diagnosis import LLMDiagnoser, diagnose_batch
    from agent.uplift import fit_from_history

    with open(os.path.join(ROOT, "data", "cases.json")) as fh:
        cases = json.load(fh)[:1500]
    with open(os.path.join(ROOT, "data", "ground_truth.json")) as fh:
        truth = json.load(fh)

    llm = LLMDiagnoser()
    diags = diagnose_batch(cases, llm)
    model = fit_from_history(llm)

    est = np.array([model.estimate_p_natural(c, diags[c["case_id"]].failure_class)
                    for c in cases])
    true = np.array([truth[c["case_id"]]["p_natural"] for c in cases])

    corr = float(np.corrcoef(est, true)[0, 1])
    mae = float(np.mean(np.abs(est - true)))
    assert corr > 0.5, f"estimate is uninformative (corr {corr:.3f})"
    assert corr < 0.99, f"estimate is suspiciously perfect (corr {corr:.3f})"
    assert mae > 0.01, f"estimate is suspiciously exact (MAE {mae:.4f})"
