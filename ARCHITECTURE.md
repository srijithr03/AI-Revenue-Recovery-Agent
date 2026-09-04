# Architecture

Nine layers, two boundaries, and a list of what is genuinely built versus what
is designed but not implemented.

---

## The layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│ L0  SYNTHETIC WORLD                            data/generator.py        │
│     16,000 cases · hidden ground truth · 25,000-record historical log   │
│     verified by data/verify_world.py before anything is built on it     │
└─────────────────────────────────────────────────────────────────────────┘
        │ observable features only
        │ ═══ GROUND-TRUTH BOUNDARY ═══  nothing below may read p_natural,
        │     p_treated, true_failure_class or annoyance_prone
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L1  DIAGNOSIS                                  agent/diagnosis.py       │
│     mapped gateway code → lookup table        (10,155 of 12,000)        │
│     unmapped free text   → LLM proposal       (1,845 of 12,000)         │
│     ─── LLM BOUNDARY ─── every proposal validated against a closed enum │
│     output: failure class · confidence · ≤3 signals · path              │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L2  UPLIFT SCORING                             agent/uplift.py          │
│     p_natural  ← logistic regression on the untreated historical slice  │
│     uplift     ← shrunk table over (predicted class × segment × action) │
│     output: uplift and treated probability per candidate action         │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L3  VALUATION AND ALLOCATION                   agent/valuation.py       │
│     incremental EV = amount × uplift − cost(action)                     │
│     greedy allocation on MARGINAL gain over the free action already     │
│     assigned — not on absolute case value                               │
│     two EV floors: ₹0.50 zero-contact, ₹50 contact                      │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L4  POLICY ENGINE            agent/policy.py + agent/policy.yaml        │
│     fully deterministic · no LLM · TOTAL evaluation                     │
│     8 rules → ALLOW / ESCALATE / BLOCK, every result recorded           │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L5  STATE MACHINE                              agent/state_machine.py   │
│     enumerated transitions — anything else raises                       │
│     bounded retries · sequential escalation · 9 stopping conditions     │
│     executors: agent/executors/{simulator, razorpay_test}.py            │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L6  VERIFICATION                               agent/verification.py    │
│     attempted ≠ payment_success ≠ confirmed_recovery                    │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L7  AUDIT TRAIL                                agent/audit.py           │
│     append-only, per case, per arm · millisecond timestamps             │
└─────────────────────────────────────────────────────────────────────────┘
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L8  EVALUATION                    eval/harness.py · run_eval.py         │
│     three arms · stratified assignment · paired counterfactual          │
│     bootstrap + Wilson intervals · two sensitivity sweeps               │
│     may read ground truth — it is the scorer                            │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Boundary 1 — the LLM never touches money

The single most important architectural decision.

**The LLM may:** reason over unstructured gateway text, and propose a failure
class with a confidence and supporting signals.

**The LLM may not:** compute any financial figure, approve any action, modify a
retry or contact counter, trigger a state transition, call a payment API, or
override a policy rule.

Every model output enters the system as a **proposal**. `validate_llm_proposal`
rejects it unless the class is a member of `DIAGNOSIS_OUTPUTS`, the confidence is
a real number in [0, 1], and the signals are truncated to three. Anything else
is discarded and the deterministic fallback runs.

Downstream, R8 rejects any action outside the permitted enumeration in
`policy.yaml`. `tests/test_policy.py` covers invented-but-plausible actions
(`send_email_reminder`), case variants (`SMS_PAYMENT_LINK`), injection-shaped
strings (`no_action; refund_customer(100000)`), and a fake inaction string
(`no_action_really`) that must not inherit the free pass real inaction gets.

The LLM is consulted on 15% of records — those with no usable error code.
Sending `INSUFFICIENT_FUNDS` to a language model would be waste dressed as
sophistication.

---

## Boundary 2 — ground truth never crosses down

Hidden ground truth lives in `data/ground_truth.json`, a separate file from
`data/cases.json`. Two components may open it: the L0 simulator (which needs the
probabilities to sample outcomes) and the L8 scorer (which needs the true class
to measure accuracy). Nothing in the decision path may.

The agent is fitted only on `data/history.json` — 25,000 past failed payments,
each with a **randomised action** and an **observed binary outcome**, and no
probabilities at all. Because actions were assigned at random, the difference in
outcome rates between a treated cell and its untreated counterpart is an
unbiased estimate of that cell's uplift.

Three further properties keep it non-circular:

- The historical log is drawn from a **different seed offset** than the
  evaluation world, so no evaluation case appears in it.
- The uplift table is keyed on the **predicted** failure class, not the true one.
  L1 runs over the historical log first, exactly as it must at inference time.
- The hidden annoyance trait is **probabilistic given its observable proxy**
  (P = 0.38 inside the fragile segment, 0.035 outside). The agent can learn the
  average effect over the segment and can never identify the trait per customer.
  That irreducible gap is what makes the agent capable of being wrong.

`tests/test_ground_truth_boundary.py` enforces all of it — including a
behavioural test that corrupts `ground_truth.json` on disk and asserts the plans
come out byte-identical.

---

## Why the layers are split where they are

**L1 and L2 are separate.** Diagnosis answers "what went wrong"; uplift answers
"what would help". Conflating them produces a model that cannot explain itself.
This split earned its keep: the obvious reading of the contradictory-signal rule
is to reclassify a chronically-failing instrument as `repeated_failure`.
Measured on the training split, that override fired on 192 cases and was right
44.8% of the time against 55.2% for simply trusting the gateway code — it cost
accuracy. What ships is a confidence downgrade to the measured 0.55, with both
signals recorded. The action consequence (retrying a chronic failer is
pointless) is handled in L2, where the uplift table is keyed by segment and
`fragile` already captures that history.

**L3 and L4 are separate.** Valuation says what is *worth* doing; policy says
what is *permitted*. Merging them would let the agent rationalise past a limit —
a case with enormous expected value still loses to a single failed rule.

**L4 is deterministic and total.** Every rule is evaluated on every case and the
result recorded even when it passes. That is what makes "8 rules evaluated,
71,168 evaluations, 0 unpermitted actions executed" a measurement rather than a
badge, and it is why the case-detail policy trace shows rules that *passed*, not
only those that failed.

**L6 is separate from L5.** Executing an action is not evidence it worked. The
separation is what permits reporting attempted (7,053), succeeded (3,937) and
confirmed (3,561) as three distinct quantities. The gap between the last two is
successes that landed outside the 72-hour window or were later reversed.

---

## Two design decisions worth defending

### Greedy allocation, not an exact solver

Contacts are ranked by marginal gain and assigned greedily until the budget is
exhausted. Greedy is provably optimal for the *fractional* knapsack, not the 0/1
case this actually is, so "optimal" would be the wrong word. It is chosen
because an exact solver would buy a marginal amount of EV at a real cost in
explainability, and because the ranking is stable enough that the difference
sits inside evaluation noise. The budget cutoff is recorded per case — rank *n*
of *m*, and the marginal gain at the cutoff — so a rejected contact can always
be traced to the number that rejected it.

### R2 blocks every action, including human escalation

A case at or above risk 0.7 is blocked outright rather than routed to a human.
This is deliberately conservative and it costs the agent recovery: `risk_blocked`
is the one class where `human_escalation` is the only action with real uplift,
and R2 refuses it on 4,974 candidate actions. The alternative — permitting
escalation because routing to a person is the safe response to risk — is
defensible, and would improve the agent's numbers. It was not adopted because a
recovery agent that finds a way to keep acting on high-risk cases is the wrong
default, and because "the system can give up" is a property worth demonstrating.
Those cases surface in the blocked list where a human can see them.

---

## Built versus designed

Nothing in this document describes a component that does not exist. To be
explicit about the line:

**Built and exercised in every run:** the generator and its property gates; both
diagnosis paths *and all three fallback paths*; the uplift model and its
calibration; valuation, allocation and the budget cutoff; all eight policy rules;
the state machine including sequential escalation and nine stopping conditions;
the simulator executor; verification; the audit trail; the three-arm harness in
both designs; both sensitivity sweeps; the API and all three UI screens.

**Built but not exercised in this run, and disclosed everywhere:**

- The **live LLM path** (`LLMDiagnoser.diagnose_one`) makes real Anthropic API
  calls with a structured prompt, thread-pooled concurrency and an on-disk
  cache. No `ANTHROPIC_API_KEY` was present, so all 1,845 ambiguous cases took
  the keyword fallback. The *validation* logic that guards the boundary is
  exercised regardless, and is covered by tests.
- The **Razorpay test-mode executor** creates real Orders and Payment Links and
  records their IDs and latencies. It refuses any key that is not `rzp_test_`.
  No credentials were present, so `razorpay_test_cases` is 0 and every case
  record carries `execution_mode: "simulated"`.

**Designed but not implemented:** subscription dunning, B2B receivables chasing,
mandate retry sequencing, checkout drop-off recovery, Hinglish voice recovery,
promise-to-pay tracking. Each additional domain multiplies the evaluation
surface; the scope boundary was held on purpose.

**Deliberately not used, and why:** no agent framework — the state machine is a
few hundred lines and explicit control flow is exactly what should be legible
here; a framework would obscure it. No vector database — nothing needs semantic
retrieval. No websockets — the batch writes results and the UI reads them. No
Docker — it adds setup friction for someone cloning the repo. No authentication.

---

## Data flow in one paragraph

`data/generator.py` writes `cases.json` (observable), `ground_truth.json`
(hidden) and `history.json` (the exploration log). `eval/run_eval.py` diagnoses
the holdout, fits the uplift model on the history, runs all three arms in both
designs, computes calibration and both sweeps, and writes four artifacts to
`eval/results/`. `api/main.py` serves those artifacts read-only, re-reading them
whenever their mtime changes. The UI renders them and **computes nothing** — if
a screen needs a number that is not in an artifact, the fix belongs in
`run_eval.py`, because the moment the frontend calculates something that number
stops being reproducible from the seed.
