"""L3 -- Valuation and allocation.

Valuation says what is WORTH doing. Policy (L4) says what is PERMITTED. They
are kept separate so the agent can never rationalise its way past a limit: a
case with enormous expected value still loses to a single failed rule.

The allocation is the part that makes this a constrained optimisation rather
than a pipeline. Given a finite contact budget B, the agent must decide which
customers are worth spending a contact on, and the ranking is by MARGINAL gain
-- how much a contact adds over the free retry that case is already getting --
not by the absolute value of the case.

That distinction is the whole thesis in one line. A Rs 50,000 payment whose
contact adds only Rs 20 over a free retry loses to a Rs 3,000 payment whose
contact adds Rs 800.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.constants import ACTIONS, CONTACT_ACTIONS
from agent.policy import ALLOW, BLOCK, ESCALATE, PolicyContext, PolicyEngine
from agent.uplift import CaseScore

# ===========================================================================
# Cost model.  Every figure documented in data/ASSUMPTIONS.md (A10-A12).
# ===========================================================================

SEND_COST = {
    "no_action": 0.0,
    "retry_immediate": 2.00,          # per-attempt gateway processing
    "retry_delayed": 2.00,
    "sms_payment_link": 0.25,         # bulk transactional SMS
    "whatsapp_nudge": 0.85,           # business messaging, marketing category
    "method_update_request": 0.85,    # delivered over the same rich channel
    "human_escalation": 120.00,       # loaded cost of an agent's time
}

# A10 -- the single most load-bearing assumption in the project. Charged on top
# of send cost for every action that touches the customer. It is what makes the
# agent decline low-value contacts, and it is swept in the sensitivity analysis
# rather than defended.
DEFAULT_ANNOYANCE_COST = 40.0


def action_cost(action: str, annoyance_cost: float = DEFAULT_ANNOYANCE_COST) -> float:
    cost = SEND_COST.get(action, 0.0)
    if action in CONTACT_ACTIONS:
        cost += annoyance_cost
    return cost


# ===========================================================================

@dataclass
class Alternative:
    """One scored action for one case, selected or rejected with a reason."""
    action: str
    uplift: float
    p_natural: float
    p_treated: float
    cost: float
    consumes_contact: bool
    incremental_ev: float
    selected: bool = False
    rejection_type: str | None = None     # ev_floor | budget_cutoff | policy | lower_ev
    rejection_detail: str = ""
    policy_outcome: str = ALLOW
    blocked_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "uplift": round(self.uplift, 4),
            "p_natural": round(self.p_natural, 4),
            "p_treated": round(self.p_treated, 4),
            "cost": round(self.cost, 2),
            "consumes_contact": self.consumes_contact,
            "incremental_ev": round(self.incremental_ev, 2),
            "selected": self.selected,
            "rejection_type": self.rejection_type,
            "rejection_detail": self.rejection_detail,
            "policy_outcome": self.policy_outcome,
            "blocked_by": self.blocked_by,
        }


@dataclass
class Plan:
    """What the agent intends to do about one case."""
    case_id: str
    action: str = "no_action"
    incremental_ev: float = 0.0
    uplift: float = 0.0
    p_natural: float = 0.0
    p_treated: float = 0.0
    segment: str = "standard"
    failure_class: str = "unknown"
    requires_approval: bool = False

    # The standby contact to reconsider once free retries are exhausted (L5).
    escalation_action: str | None = None
    escalation_ev: float = 0.0
    escalation_uplift: float = 0.0

    budget_rank: int | None = None
    budget_contenders: int = 0
    budget_cutoff_ev: float | None = None
    won_contact: bool = False

    alternatives: list[Alternative] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "action": self.action,
            "incremental_ev": round(self.incremental_ev, 2),
            "uplift": round(self.uplift, 4),
            "p_natural": round(self.p_natural, 4),
            "p_treated": round(self.p_treated, 4),
            "segment": self.segment,
            "failure_class": self.failure_class,
            "requires_approval": self.requires_approval,
            "escalation_action": self.escalation_action,
            "escalation_ev": round(self.escalation_ev, 2),
            "escalation_uplift": round(self.escalation_uplift, 4),
            "budget_rank": self.budget_rank,
            "budget_contenders": self.budget_contenders,
            "budget_cutoff_ev": (round(self.budget_cutoff_ev, 2)
                                 if self.budget_cutoff_ev is not None else None),
            "won_contact": self.won_contact,
        }


# ===========================================================================

class Allocator:
    def __init__(self, engine: PolicyEngine,
                 annoyance_cost: float = DEFAULT_ANNOYANCE_COST) -> None:
        self.engine = engine
        self.annoyance_cost = annoyance_cost

    # ---------------------------------------------------------------- scoring

    def score_alternatives(self, case: dict[str, Any], cs: CaseScore) -> list[Alternative]:
        """Every action, valued and policy-checked. Nothing is filtered out here
        -- rejected options are kept, with the reason that rejected them, because
        that table is the visible proof of the decision process."""
        amount = float(case["amount"])
        out: list[Alternative] = []

        for act in ACTIONS:
            sc = cs.actions[act]
            cost = action_cost(act, self.annoyance_cost)
            ev = amount * sc.uplift - cost

            decision = self.engine.evaluate(
                case, act, PolicyContext(intended_hour=int(case.get("hour", 12))))

            alt = Alternative(
                action=act,
                uplift=sc.uplift,
                p_natural=cs.p_natural,
                p_treated=sc.p_treated,
                cost=cost,
                consumes_contact=sc.consumes_contact,
                incremental_ev=ev,
                policy_outcome=decision.outcome,
                blocked_by=decision.blocked_by,
            )
            if decision.outcome == BLOCK:
                alt.rejection_type = "policy"
                alt.rejection_detail = f"blocked by {decision.blocked_by}: {decision.block_detail}"
            out.append(alt)

        return out

    # ---------------------------------------------------------------- planning

    def plan_batch(self, cases: list[dict[str, Any]],
                   scores: dict[str, CaseScore],
                   budget: int | None = None) -> dict[str, Plan]:
        """Greedy allocation of a finite contact budget on MARGINAL value.

        Greedy is not provably optimal here -- this is a 0/1 knapsack, not the
        fractional one, so "optimal" would be the wrong word. It is chosen
        because an exact solver would buy a marginal amount of EV at a real cost
        in explainability, and because the ranking is stable enough that the
        difference sits inside evaluation noise.
        """
        budget = self.engine.contact_budget_per_batch if budget is None else budget
        plans: dict[str, Plan] = {}
        contenders: list[tuple[float, str, Alternative]] = []

        floor_contact = self.engine.ev_floor_contact
        floor_zero = self.engine.ev_floor_zero_contact

        for case in cases:
            cid = case["case_id"]
            cs = scores[cid]
            alts = self.score_alternatives(case, cs)
            by_action = {a.action: a for a in alts}

            plan = Plan(case_id=cid, p_natural=cs.p_natural, segment=cs.segment,
                        failure_class=cs.failure_class, alternatives=alts)

            allowed = [a for a in alts if a.rejection_type != "policy"
                       and a.action != "no_action"]

            # ---- step 1-2: the best zero-contact action, assigned freely -----
            zero = [a for a in allowed if not a.consumes_contact]
            best_zero = max(zero, key=lambda a: a.incremental_ev, default=None)
            if best_zero is not None and best_zero.incremental_ev >= floor_zero:
                plan.action = best_zero.action
                plan.incremental_ev = best_zero.incremental_ev
                plan.uplift = best_zero.uplift
                plan.p_treated = best_zero.p_treated
                plan.requires_approval = best_zero.policy_outcome == ESCALATE
            else:
                for a in zero:
                    if a.rejection_type is None and a.incremental_ev < floor_zero:
                        a.rejection_type = "ev_floor"
                        a.rejection_detail = (
                            f"incremental EV {a.incremental_ev:.2f} below the "
                            f"{floor_zero:.2f} floor for zero-contact actions")

            # ---- step 3: marginal value of the best contact -------------------
            contact = [a for a in allowed if a.consumes_contact]
            best_contact = max(contact, key=lambda a: a.incremental_ev, default=None)

            baseline_ev = plan.incremental_ev if plan.action != "no_action" else 0.0

            if best_contact is not None:
                marginal = best_contact.incremental_ev - baseline_ev
                if best_contact.incremental_ev < floor_contact:
                    best_contact.rejection_type = "ev_floor"
                    best_contact.rejection_detail = (
                        f"incremental EV {best_contact.incremental_ev:.2f} below the "
                        f"{floor_contact:.2f} floor for contact actions")
                elif marginal <= 0:
                    best_contact.rejection_type = "lower_ev"
                    best_contact.rejection_detail = (
                        f"adds {marginal:.2f} over {plan.action}, which is free")
                else:
                    contenders.append((marginal, cid, best_contact))

                # Standby escalation candidate: worth reconsidering once the
                # free retries are spent, even if it loses now (spec 8.5).
                plan.escalation_action = best_contact.action
                plan.escalation_ev = best_contact.incremental_ev
                plan.escalation_uplift = best_contact.uplift

            # Everything not selected and not otherwise rejected simply lost.
            for a in alts:
                if a.rejection_type is None and not a.selected and a.action != plan.action:
                    if a.action == "no_action":
                        continue
                    a.rejection_type = "lower_ev"
                    a.rejection_detail = (
                        f"incremental EV {a.incremental_ev:.2f} below the "
                        f"selected action at {plan.incremental_ev:.2f}")

            plans[cid] = plan

        # ---- steps 4-6: rank by marginal gain, spend the budget --------------
        contenders.sort(key=lambda t: -t[0])
        n_contenders = len(contenders)
        cutoff_ev = (contenders[budget - 1][0]
                     if 0 < budget <= n_contenders else None)

        for rank, (marginal, cid, alt) in enumerate(contenders, start=1):
            plan = plans[cid]
            plan.budget_rank = rank
            plan.budget_contenders = n_contenders
            plan.budget_cutoff_ev = cutoff_ev

            if rank <= budget:
                # The contact wins the slot and replaces the free retry. The
                # displaced action must be given a computed reason -- otherwise
                # it appears in the alternatives table as neither selected nor
                # rejected, which is a hole in the one view that is supposed to
                # account for every option.
                displaced = plan.action
                for a in plan.alternatives:
                    a.selected = False
                    if (a.action == displaced and displaced != "no_action"
                            and a.rejection_type is None):
                        a.rejection_type = "lower_ev"
                        a.rejection_detail = (
                            f"superseded by {alt.action}, which adds "
                            f"{marginal:.2f} more at rank {rank} of "
                            f"{n_contenders}")
                alt.selected = True
                alt.rejection_type = None
                alt.rejection_detail = ""
                plan.action = alt.action
                plan.incremental_ev = alt.incremental_ev
                plan.uplift = alt.uplift
                plan.p_treated = alt.p_treated
                plan.won_contact = True
                plan.requires_approval = alt.policy_outcome == ESCALATE
                plan.escalation_action = None
                plan.escalation_ev = 0.0
            else:
                alt.rejection_type = "budget_cutoff"
                alt.rejection_detail = (
                    f"rank {rank} of {n_contenders} contenders, budget {budget}; "
                    f"marginal gain {marginal:.2f} below the cutoff at "
                    f"{cutoff_ev:.2f}" if cutoff_ev is not None else
                    f"rank {rank} of {n_contenders} contenders, budget {budget}")

        # Mark the finally-selected action on every plan.
        for plan in plans.values():
            for a in plan.alternatives:
                if a.action == plan.action:
                    a.selected = True
                    a.rejection_type = None
                    a.rejection_detail = ""
        return plans
