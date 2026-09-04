"""Shared enumerations and constants.

This module is deliberately dependency-free. Both the generator (L0) and the
agent layers (L1-L5) import from here so that the *names* of things agree,
while the *values* of hidden ground truth never cross the boundary.
"""

# ---------------------------------------------------------------- failure classes

FAILURE_CLASSES = (
    "temporary_failure",
    "insufficient_funds",
    "invalid_method",
    "authentication_failure",
    "risk_blocked",
    "repeated_failure",
)

# `unknown` is a first-class diagnosis output (explicit abstention), but it is
# never a *true* class -- the world always knows what actually went wrong.
DIAGNOSIS_OUTPUTS = FAILURE_CLASSES + ("unknown",)

FAILURE_CLASS_LABELS = {
    "temporary_failure": "Temporary failure",
    "insufficient_funds": "Insufficient funds",
    "invalid_method": "Invalid method",
    "authentication_failure": "Authentication failure",
    "risk_blocked": "Risk blocked",
    "repeated_failure": "Repeated failure",
    "unknown": "Unknown",
}

# ---------------------------------------------------------------- actions

ACTIONS = (
    "no_action",
    "retry_immediate",
    "retry_delayed",
    "sms_payment_link",
    "whatsapp_nudge",
    "method_update_request",
    "human_escalation",
)

# Actions that consume the finite customer-contact budget.
CONTACT_ACTIONS = frozenset(
    {"sms_payment_link", "whatsapp_nudge", "method_update_request", "human_escalation"}
)

# Actions that re-attempt the payment without touching the customer.
RETRY_ACTIONS = frozenset({"retry_immediate", "retry_delayed"})

TREATMENT_ACTIONS = tuple(a for a in ACTIONS if a != "no_action")

ACTION_LABELS = {
    "no_action": "No action",
    "retry_immediate": "Retry immediate",
    "retry_delayed": "Retry delayed",
    "sms_payment_link": "SMS payment link",
    "whatsapp_nudge": "WhatsApp nudge",
    "method_update_request": "Method update request",
    "human_escalation": "Human escalation",
}

# ---------------------------------------------------------------- payment methods

METHODS = ("upi", "card", "netbanking", "wallet")

# ---------------------------------------------------------------- customer segments

SEGMENTS = ("fragile", "loyal", "standard")


def segment_of(prior_success: int, prior_failures: int, tenure_days: int) -> str:
    """Customer segment from OBSERVABLE features only.

    Order matters: fragility dominates loyalty, because a customer with a long
    history who has started failing repeatedly is a fragile customer now.
    """
    if prior_failures >= 3 or tenure_days < 30:
        return "fragile"
    if prior_success >= 3:
        return "loyal"
    return "standard"


# ---------------------------------------------------------------- states

STATES = (
    "FAILED",
    "DIAGNOSED",
    "SCORED",
    "ELIGIBLE",
    "INELIGIBLE",
    "POLICY_CHECKED",
    "APPROVED",
    "ESCALATED",
    "BLOCKED",
    "EXECUTING",
    "WAITING",
    "OUTCOME_CHECK",
    "RECOVERED",
    "RETRYABLE",
    "STOPPED",
)

TERMINAL_STATES = frozenset({"RECOVERED", "STOPPED", "ESCALATED", "INELIGIBLE"})

ARMS = ("control", "naive", "agent")
