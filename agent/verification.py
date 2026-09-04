"""L6 -- Outcome verification.

Three quantities that are routinely conflated, kept apart here because
conflating them is how recovery numbers get inflated:

    attempted_recovery  an action was executed
    payment_success     the payment subsequently succeeded
    confirmed_recovery  that success is attributable to THIS case, landed
                        inside the observation window, and was not reversed

Reporting only ``payment_success`` inflates -- it counts successes that were
going to happen anyway or that belong to a different transaction. Reporting
only ``confirmed_recovery`` hides the error rate. The batch summary reports all
three, separately.

Verification is deliberately a separate layer from execution. Executing an
action is not evidence that it worked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A13 -- recovery counts only inside this window. Matches the policy engine's
# max case age, so the two cannot disagree.
OBSERVATION_WINDOW_HOURS = 72.0

# A small share of apparent successes are later reversed (chargeback, failed
# settlement, duplicate). Modelling this is what stops `payment_success` from
# being treated as final.
REVERSAL_RATE = 0.012


@dataclass
class Verification:
    attempted: bool
    payment_success: bool
    confirmed: bool
    reason: str
    amount_confirmed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "payment_success": self.payment_success,
            "confirmed": self.confirmed,
            "reason": self.reason,
            "amount_confirmed": round(self.amount_confirmed, 2),
        }


def verify(case: dict[str, Any], attempted: bool, payment_success: bool,
           hours_elapsed: float, reversed_flag: bool = False) -> Verification:
    """Turn a raw success flag into a confirmed, attributable recovery."""
    amount = float(case.get("amount", 0.0))

    if not payment_success:
        return Verification(attempted, False, False,
                            "no successful payment observed in window")

    if hours_elapsed > OBSERVATION_WINDOW_HOURS:
        return Verification(
            attempted, True, False,
            f"success landed {hours_elapsed:.1f}h after failure, outside the "
            f"{OBSERVATION_WINDOW_HOURS:.0f}h window; not attributable")

    if reversed_flag:
        return Verification(attempted, True, False,
                            "payment succeeded then was reversed")

    return Verification(attempted, True, True, "confirmed inside window", amount)
