"""Numbers for the explainer screen.

The explainer exists to make the uplift idea legible before a judge reaches the
console. It must therefore carry real figures -- an explanation illustrated with
invented numbers is worth less than no explanation, because a judge who checks
one against the console and finds it stale stops trusting both.

So it obeys the same rule as every other screen: the UI computes nothing. This
module picks the illustrative cases out of the finished run and writes them into
summary.json, which means `make eval` keeps the explanation true for free and
the reproducibility claim covers it.

Nothing here reads ground truth. It selects from artifacts the agent already
produced.
"""

from __future__ import annotations

import statistics as st
from typing import Any

from agent.constants import CONTACT_ACTIONS


def _median_case(cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The case whose uplift sits closest to the population median.

    The median rather than a hand-picked dramatic one: the panel should see a
    typical decision, and a cherry-picked example is exactly the move the rest
    of the project refuses to make.
    """
    scored = [c for c in cases
              if c.get("uplift") is not None and c.get("p_natural") is not None
              and c.get("p_treated") is not None and c["uplift"] > 0]
    if not scored:
        return None
    target = st.median([c["uplift"] for c in scored])
    return min(scored, key=lambda c: abs(c["uplift"] - target))


def _ev_example(cases: list[dict[str, Any]],
                alternatives: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """A case whose action table shows a real spread of economic value.

    Wants a case where several actions were genuinely scored, so the table shows
    a ranking rather than one action and a row of zeroes.
    """
    eligible = []
    for c in cases:
        alts = alternatives.get(c["case_id"]) or []
        positive = [a for a in alts if a["incremental_ev"] > 0]
        # Needs a real ranking AND an action actually taken. An earlier version
        # ranked by widest EV spread, which selected the largest policy-BLOCKED
        # case in the batch -- a table of scored actions with nothing chosen,
        # which illustrates the wrong thing.
        if len(positive) < 4 or not c.get("action"):
            continue
        if not any(a["selected"] for a in alts):
            continue
        eligible.append((c, alts))
    if not eligible:
        return None
    # The case nearest the median amount, not the largest. A six-figure outlier
    # makes the arithmetic look impressive and the batch look unrepresentative.
    target = st.median([c["amount"] for c, _ in eligible])
    c, alts = min(eligible, key=lambda pair: abs(pair[0]["amount"] - target))
    return {
        "case_id": c["case_id"],
        "amount": c["amount"],
        "failure_class": c["failure_class"],
        "selected": c["action"],
        "actions": [
            {"action": a["action"], "uplift": a["uplift"], "cost": a["cost"],
             "incremental_ev": a["incremental_ev"], "selected": a["selected"]}
            for a in sorted(alts, key=lambda a: -a["incremental_ev"])
        ],
    }


def _rejection_example(cases: list[dict[str, Any]],
                       alternatives: dict[str, list[dict[str, Any]]]
                       ) -> dict[str, Any] | None:
    """The case that lost a contact to the budget by the narrowest margin.

    This is the thesis in one row: a contact action with HIGHER absolute EV than
    the action actually taken, declined because its MARGINAL gain over the free
    action fell below the batch cutoff.

    Selecting the narrowest miss is deliberate. The closer the margin, the
    harder it is to dismiss the decision as obvious -- and the number comes from
    the run rather than from a choice made while writing the page.
    """
    best = None
    for cid, alts in alternatives.items():
        c = next((x for x in cases if x["case_id"] == cid), None)
        if not c or not c.get("budget_rank") or not c.get("budget_cutoff_ev"):
            continue
        selected = next((a for a in alts if a["selected"]), None)
        if selected is None or selected["action"] in CONTACT_ACTIONS:
            continue
        lost = [a for a in alts
                if a["action"] in CONTACT_ACTIONS
                and a["incremental_ev"] > selected["incremental_ev"]]
        if not lost:
            continue
        top = max(lost, key=lambda a: a["incremental_ev"])
        margin = top["incremental_ev"] - selected["incremental_ev"]
        miss = c["budget_cutoff_ev"] - margin
        if miss < 0:
            continue
        if best is None or miss < best[0]:
            best = (miss, c, selected, top, margin)
    if best is None:
        return None
    miss, c, selected, top, margin = best
    return {
        "case_id": c["case_id"],
        "amount": c["amount"],
        "failure_class": c["failure_class"],
        "selected_action": selected["action"],
        "selected_ev": round(selected["incremental_ev"], 2),
        "rejected_action": top["action"],
        "rejected_ev": round(top["incremental_ev"], 2),
        "rejected_uplift": top["uplift"],
        "selected_uplift": selected["uplift"],
        "marginal_gain": round(margin, 2),
        "cutoff_ev": c["budget_cutoff_ev"],
        "missed_by": round(miss, 2),
        "rank": c["budget_rank"],
        "contenders": c["budget_contenders"],
    }


def build(cases: list[dict[str, Any]], alternatives: dict[str, list[dict[str, Any]]],
          contacts_used: int, budget: int) -> dict[str, Any]:
    """Everything the explainer screen renders, resolved from this run."""
    med = _median_case(cases)
    contenders = max((c.get("budget_contenders") or 0) for c in cases) or None

    return {
        "uplift_example": None if med is None else {
            "case_id": med["case_id"],
            "amount": med["amount"],
            "failure_class": med["failure_class"],
            "action": med["action"],
            "p_natural": med["p_natural"],
            "p_treated": med["p_treated"],
            "uplift": med["uplift"],
            "is_median": True,
        },
        "population": {
            "median_p_natural": round(
                st.median([c["p_natural"] for c in cases if c.get("p_natural")]), 4),
            "median_uplift": round(
                st.median([c["uplift"] for c in cases
                           if c.get("uplift") is not None and c["uplift"] > 0]), 4),
        },
        "ev_example": _ev_example(cases, alternatives),
        "budget": {
            "contenders": contenders,
            "contacts_used": contacts_used,
            "budget": budget,
        },
        "rejection_example": _rejection_example(cases, alternatives),
    }
