"""L1 -- Failure diagnosis.

Two paths by design:

  * DETERMINISTIC.  Gateway error codes that map unambiguously go through a
    lookup table.  This covers ~85% of records and costs nothing.  Sending
    `INSUFFICIENT_FUNDS` to a language model would be waste dressed as
    sophistication.

  * LLM.  Records carrying only free text go to Claude with a structured prompt
    and a closed list of permitted classes.

The LLM returns a PROPOSAL.  It is validated against the permitted enumeration
before it is allowed to affect anything (spec Part 4.1 -- the LLM boundary).

Every external call has a designed fallback.  A batch never halts because a
model call failed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Any

from agent.constants import DIAGNOSIS_OUTPUTS, FAILURE_CLASSES

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "..", "data", "llm_cache.json")

MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Confidence constants.
#
# These were FIT ON THE TRAINING SPLIT ONLY (see eval/calibration.py) and are
# deliberately not per-case: they are the base rate of being right on each path.
# The reliability plot on the evaluation screen is the check on whether they are
# honest.
# ---------------------------------------------------------------------------
CONF_MAPPED_CODE = 0.93        # measured 0.9275 on 3,216 clean mapped cases
CONF_CONTRADICTION = 0.55      # measured 0.552 on 192 contradicted cases
CONF_LLM_DEFAULT = 0.70        # used when a model returns an unusable confidence
CONF_FALLBACK_KEYWORD = 0.55   # keyword heuristic matched something
CONF_FALLBACK_NONE = 0.30      # nothing matched -> abstain

# ---------------------------------------------------------------------------
# Deterministic path
# ---------------------------------------------------------------------------

CODE_TO_CLASS: dict[str, str] = {
    # temporary
    "GW_TIMEOUT": "temporary_failure",
    "BANK_UNAVAILABLE": "temporary_failure",
    "UPI_TXN_TIMEOUT": "temporary_failure",
    "GATEWAY_ERROR": "temporary_failure",
    # funds
    "INSUFFICIENT_FUNDS": "insufficient_funds",
    "NO_BALANCE": "insufficient_funds",
    "U31": "insufficient_funds",
    # instrument
    "CARD_EXPIRED": "invalid_method",
    "INVALID_VPA": "invalid_method",
    "ACCOUNT_CLOSED": "invalid_method",
    "MANDATE_REVOKED": "invalid_method",
    # auth
    "OTP_TIMEOUT": "authentication_failure",
    "3DS_FAILED": "authentication_failure",
    "PIN_INCORRECT": "authentication_failure",
    "AUTH_ABANDONED": "authentication_failure",
    # risk
    "RISK_DECLINED": "risk_blocked",
    "FRAUD_SUSPECTED": "risk_blocked",
    "VELOCITY_LIMIT": "risk_blocked",
    # repeat
    "REPEAT_DECLINE": "repeated_failure",
}

# Threshold at which a prior-failure history overrides a clean gateway code.
CONTRADICTION_PRIOR_FAILURES = 4

# ---------------------------------------------------------------------------
# Keyword heuristic -- the fallback when the LLM is unavailable or unusable.
# Ordered: the first pattern that matches wins, so more specific causes are
# tested before more general ones.
# ---------------------------------------------------------------------------

KEYWORD_RULES: list[tuple[str, str]] = [
    (r"no longer active|not in a usable state|can no longer be used|"
     r"could not be validated|expired|closed", "invalid_method"),
    (r"did not complete the required verification|verification was not|"
     r"authorisation was not confirmed|security check was not|otp|pin",
     "authentication_failure"),
    (r"internal checks|stopped before reaching|could not be processed for this account",
     "risk_blocked"),
    (r"multiple recent attempts|declined on prior attempts|prior attempts",
     "repeated_failure"),
    (r"issuing bank declined|not permitted on this account|unable to authorise|"
     r"declined by the account holder|different account|insufficient|balance",
     "insufficient_funds"),
    (r"try again later|temporarily unable|connectivity|no response was received|"
     r"reattempt|timed out|timeout|unavailable", "temporary_failure"),
]


@dataclass
class Diagnosis:
    """The L1 output contract."""
    failure_class: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    path: str = "rules"          # rules | llm | fallback_keyword | fallback_none
    llm_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Validation of model output -- mandatory before anything downstream sees it
# ---------------------------------------------------------------------------

def validate_llm_proposal(raw: Any) -> Diagnosis | None:
    """Turn a raw model response into a Diagnosis, or None if unusable.

    Never trust: the class must be a member of the permitted enumeration, the
    confidence must be a real number in [0,1], and signals are truncated to
    three short strings.  Anything else is discarded and the caller falls back.
    """
    if isinstance(raw, str):
        text = raw.strip()
        # Models sometimes wrap JSON in fences despite being told not to.
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    if not isinstance(raw, dict):
        return None

    cls = raw.get("failure_class")
    if not isinstance(cls, str) or cls not in DIAGNOSIS_OUTPUTS:
        return None

    conf = raw.get("confidence", CONF_LLM_DEFAULT)
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        conf = CONF_LLM_DEFAULT
    conf = float(conf)
    if not (0.0 <= conf <= 1.0):
        conf = CONF_LLM_DEFAULT

    signals = raw.get("signals", [])
    if not isinstance(signals, list):
        signals = []
    clean = [str(s)[:120] for s in signals if isinstance(s, (str, int, float))][:3]

    return Diagnosis(failure_class=cls, confidence=conf, signals=clean, path="llm")


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------

def keyword_fallback(message: str, reason: str) -> Diagnosis:
    """Degrade gracefully, at LOWERED confidence.

    The point is not to match the LLM. It is to keep the batch moving and to be
    honest, in the confidence value, that this was a downgraded decision.
    """
    text = (message or "").lower()
    for pattern, cls in KEYWORD_RULES:
        if re.search(pattern, text):
            return Diagnosis(
                failure_class=cls,
                confidence=CONF_FALLBACK_KEYWORD,
                signals=[f"keyword heuristic matched {cls}", f"llm unavailable: {reason}"],
                path="fallback_keyword",
                llm_error=reason,
            )
    return Diagnosis(
        failure_class="unknown",
        confidence=CONF_FALLBACK_NONE,
        signals=["no keyword matched", f"llm unavailable: {reason}"],
        path="fallback_none",
        llm_error=reason,
    )


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You classify failed payment records for an Indian payments \
merchant. You are given a free-text gateway message that carries no usable error \
code, plus a short summary of the customer history.

Choose exactly one failure class from this closed list:

- temporary_failure: transient gateway, network or bank issue, likely to clear on its own
- insufficient_funds: the account or instrument lacked balance
- invalid_method: expired card, closed account, dead VPA, or revoked mandate
- authentication_failure: OTP, PIN or 3DS was not completed by the customer
- risk_blocked: declined by a risk or fraud engine
- repeated_failure: the nth consecutive failure on the same instrument, where the \
history matters more than the proximate symptom
- unknown: the message does not support any of the above

Abstaining with "unknown" is CORRECT behaviour when the evidence is genuinely \
insufficient. It is not a failure. Do not guess to appear decisive.

Respond with JSON only. No prose, no markdown fences. Exactly this shape:

{"failure_class": "<one of the list above>", "confidence": <number between 0 and 1>, \
"signals": ["<short phrase>", "<short phrase>"]}

"signals" holds at most three short phrases quoting or paraphrasing the specific \
evidence you used."""


def _user_prompt(case: dict[str, Any]) -> str:
    return (
        f"Gateway message: {case.get('gateway_message', '')!r}\n"
        f"Payment method: {case.get('method')}\n"
        f"Amount: INR {case.get('amount')}\n"
        f"Customer history: {case.get('prior_success')} prior successful payments, "
        f"{case.get('prior_failures')} prior failures on this instrument, "
        f"{case.get('tenure_days')} days with the merchant.\n"
        f"Risk score: {case.get('risk_score')}"
    )


class LLMDiagnoser:
    """Wraps the Anthropic client with caching, concurrency and a hard fallback.

    Instantiating this NEVER raises. If there is no API key, ``self.available``
    is False and every call takes the fallback path -- which is the designed
    behaviour, not an error.
    """

    def __init__(self, model: str = MODEL, use_cache: bool = True) -> None:
        self.model = model
        self.use_cache = use_cache
        self.client = None
        self.available = False
        self.unavailable_reason = "no ANTHROPIC_API_KEY in environment"
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self.stats = {"llm_ok": 0, "llm_fallback": 0, "cache_hit": 0}

        if self.use_cache and os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH) as fh:
                    self._cache = json.load(fh)
            except (OSError, json.JSONDecodeError):
                self._cache = {}

        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self.client = anthropic.Anthropic()
                self.available = True
                self.unavailable_reason = ""
            except Exception as exc:  # noqa: BLE001 - construction must not raise
                self.unavailable_reason = f"{type(exc).__name__}"

    # -- cache ---------------------------------------------------------------

    def _key(self, case: dict[str, Any]) -> str:
        blob = f"{self.model}|{case.get('gateway_message','')}|{case.get('prior_failures')}"
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    def save_cache(self) -> None:
        if not self.use_cache:
            return
        try:
            with open(CACHE_PATH, "w") as fh:
                json.dump(self._cache, fh, indent=1)
        except OSError:
            pass

    # -- single call ---------------------------------------------------------

    def diagnose_one(self, case: dict[str, Any]) -> Diagnosis:
        msg = case.get("gateway_message", "") or ""

        if self.use_cache:
            key = self._key(case)
            with self._lock:
                hit = self._cache.get(key)
            if hit is not None:
                validated = validate_llm_proposal(hit)
                if validated is not None:
                    with self._lock:
                        self.stats["cache_hit"] += 1
                    return validated

        # Failure recovery path 1: no key present.
        if not self.available or self.client is None:
            with self._lock:
                self.stats["llm_fallback"] += 1
            return keyword_fallback(msg, self.unavailable_reason)

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _user_prompt(case)}],
            )
            text = resp.content[0].text
        except Exception as exc:  # noqa: BLE001
            # Failure recovery path 2: the call raised (network, rate limit,
            # timeout, auth). Record the exception TYPE so the audit trail shows
            # what actually happened.
            with self._lock:
                self.stats["llm_fallback"] += 1
            return keyword_fallback(msg, type(exc).__name__)

        validated = validate_llm_proposal(text)
        if validated is None:
            # Failure recovery path 3: malformed or out-of-enum response.
            with self._lock:
                self.stats["llm_fallback"] += 1
            return keyword_fallback(msg, "malformed_or_out_of_enum_response")

        if self.use_cache:
            with self._lock:
                self._cache[self._key(case)] = validated.to_dict()
        with self._lock:
            self.stats["llm_ok"] += 1
        return validated

    # -- batch ---------------------------------------------------------------

    def diagnose_many(self, cases: list[dict[str, Any]], workers: int = 8
                      ) -> list[Diagnosis]:
        if not self.available:
            # No point spinning up a pool to call nothing.
            return [self.diagnose_one(c) for c in cases]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self.diagnose_one, cases))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def diagnose_rules(case: dict[str, Any]) -> Diagnosis | None:
    """The deterministic path. Returns None if the case needs the LLM."""
    code = (case.get("gateway_code") or "").strip()
    cls = CODE_TO_CLASS.get(code)
    if cls is None:
        return None

    signals = [f"gateway code {code}"]
    conf = CONF_MAPPED_CODE

    # Contradictory-signal downgrade.
    #
    # A gateway reports the PROXIMATE symptom. A card that has failed five times
    # running still returns INSUFFICIENT_FUNDS on the sixth attempt: the code is
    # accurate, and the diagnosis it implies may still be the wrong thing to act
    # on.
    #
    # We first implemented this as a CLASS OVERRIDE to `repeated_failure`, as is
    # the obvious reading. Measured on the training split, that override fired on
    # 192 cases and was right 44.8% of the time, against 55.2% for simply
    # trusting the code -- it cost 0.6 points of overall accuracy. So it does not
    # ship as an override.
    #
    # What ships is the calibrated response to genuinely conflicting evidence:
    # keep the marginally-better class, drop confidence to the measured 0.55, and
    # record BOTH signals so the conflict is visible in the audit trail.
    #
    # The action consequence -- that retrying a chronically-failing instrument is
    # pointless -- is not lost. It is handled in L2, where the uplift table is
    # keyed by customer segment and `fragile` already captures this history.
    # Pushing it into the diagnosis class would conflate "what went wrong" with
    # "what would help", which is exactly the separation L1 and L2 exist to keep.
    pf = int(case.get("prior_failures", 0))
    if pf >= CONTRADICTION_PRIOR_FAILURES and cls != "repeated_failure":
        return Diagnosis(
            failure_class=cls,
            confidence=CONF_CONTRADICTION,
            signals=[
                f"gateway code {code} implies {cls}",
                f"{pf} prior failures on this instrument contradicts it",
                "confidence downgraded; treated as chronic in uplift scoring",
            ],
            path="rules",
        )

    if pf >= 2:
        signals.append(f"{pf} prior failures (below contradiction threshold)")
    return Diagnosis(failure_class=cls, confidence=conf, signals=signals, path="rules")


def diagnose_batch(cases: list[dict[str, Any]], llm: LLMDiagnoser | None = None
                   ) -> dict[str, Diagnosis]:
    """Diagnose a whole batch, routing each case to the cheapest path that works."""
    if llm is None:
        llm = LLMDiagnoser()

    out: dict[str, Diagnosis] = {}
    needs_llm: list[dict[str, Any]] = []

    for case in cases:
        d = diagnose_rules(case)
        if d is None:
            needs_llm.append(case)
        else:
            out[case["case_id"]] = d

    if needs_llm:
        results = llm.diagnose_many(needs_llm)
        for case, d in zip(needs_llm, results):
            # The same conflicting-evidence downgrade applies on the LLM path,
            # capped so it can only ever LOWER confidence.
            pf = int(case.get("prior_failures", 0))
            if (pf >= CONTRADICTION_PRIOR_FAILURES
                    and d.failure_class not in ("repeated_failure", "unknown")
                    and d.confidence > CONF_CONTRADICTION):
                d = Diagnosis(
                    failure_class=d.failure_class,
                    confidence=CONF_CONTRADICTION,
                    signals=(d.signals[:2] +
                             [f"{pf} prior failures conflicts with {d.failure_class}"]),
                    path=d.path,
                    llm_error=d.llm_error,
                )
            out[case["case_id"]] = d

    llm.save_cache()
    return out
