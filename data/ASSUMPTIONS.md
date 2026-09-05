# Assumptions

Every number in the synthetic world and the cost model, with its reasoning, its
source where one exists, and an honest note where none does.

This document exists so that a reader can **disagree with any single assumption
without the methodology collapsing**. The three-arm evaluation design does not
depend on these values being right; it depends on them being *stated*. Where an
assumption is load-bearing for the headline result, it is swept in the
sensitivity analysis rather than defended.

Read this alongside `data/generator.py`, where each constant carries the tag
(`A1`, `A2`, ...) used below.

---

## Summary: which assumptions actually matter

| Assumption | Load-bearing? | If it is wrong by 2x, what changes |
|---|---|---|
| **A10 annoyance cost per contact (Rs 40)** | **Critical** | The headline agent-vs-naive comparison can invert. Swept across Rs 0-900 in the sensitivity analysis. |
| A1 base natural recovery by class | High | Moves all three arms together; the *deltas* between arms are far more stable than the absolute levels. |
| A4 treatment odds multipliers | High | Changes which action wins per class. The agent adapts (it fits the table from data); the naive arm does not. |
| A5 annoyance trait prevalence | Medium | Changes how much targeting is worth. More annoyance-prone customers favours the agent. |
| A9 chronic-failer share | Medium | Shifts the population toward harder cases; lowers absolute recovery in every arm. |
| A2 failure-class mix | Medium | Now calibrated to NPCI TD/BD rather than assumed. Recalibrating it moved agent-vs-naive from a tie to a significant loss, so it is not the "Low" it was rated when it was a guess. |
| A3 payment-method mix | Negligible | Method is descriptive only; nothing in the decision path keys off it. |
| A11/A12 send costs (SMS, WhatsApp) | Negligible | Dominated ~50x by the annoyance cost. See note under A10. |

---

## A1 - Base natural recovery probability, by failure class

Probability that a failed payment recovers **with no intervention at all**,
inside a 72-hour observation window, before any feature adjustment.

| Failure class | Base rate | Reasoning |
|---|---|---|
| `temporary_failure` | 0.55 | Transient bank/gateway/network issues clear on their own; the customer retries and it works. The single most self-healing category. |
| `authentication_failure` | 0.34 | Many customers simply re-enter the OTP or PIN unprompted. A large minority abandon. |
| `insufficient_funds` | 0.22 | Some customers top up and return of their own accord, typically after a salary credit. Most do not, inside 72h. |
| `repeated_failure` | 0.08 | The instrument has already demonstrated non-recovery across prior attempts. Low prior on it spontaneously starting to work. |
| `invalid_method` | 0.06 | Requires an action (update the card, re-link the VPA) that the customer will not take unprompted, because nothing has told them to. |
| `risk_blocked` | 0.03 | The risk engine will keep declining. Only a manual review changes the outcome. |

**Grounding.** No public dataset reports *untreated* recovery by decline reason
for Indian payments; this is the number the whole industry is missing, and it is
precisely why the control arm exists. What is published is the *treated* side:
industry median failed-payment recovery sits near 47.6%, smart-retry logic
recovers 45-70%, and well-configured dunning recovers 50-80%
([Baremetrics benchmarks](https://baremetrics.com/blog/subscription-payment-recovery-benchmarks),
[digitalapplied dunning playbook](https://www.digitalapplied.com/blog/failed-payment-recovery-dunning-playbook-2026)).

Those are *treated* figures and are routinely quoted as if they were caused by
the treatment. They are the exact quantity this project argues is unmeasurable
without a control group. The realised population mean of `p_natural` here is
**0.264**, and mean treated recovery lands in the 40-55% band depending on arm,
which is consistent with those published treated numbers while making explicit
that roughly half of it is natural.

**Honest note.** These six numbers are the author's estimates, informed by the
relative self-healing logic of each cause. They are not measurements. A merchant
with real data should replace them; the evaluation harness does not change.

**Direction of error.** If the true base rates are uniformly higher, all three
arms recover more and every intervention looks *less* valuable (more of the
recovery is natural). If they are uniformly lower, interventions look more
valuable. Relative arm ordering is substantially more robust than the levels.

---

## A2 - Failure-class mix

Unconditional prior: `insufficient_funds` 0.31, `authentication_failure` 0.22,
`temporary_failure` 0.19, `invalid_method` 0.12, `repeated_failure` 0.10,
`risk_blocked` 0.06. Conditioned further on customer features in
`_draw_failure_class`, so the realised mix differs (see `make verify`).

**These values were RECALIBRATED against NPCI's published decline split.** The
earlier prior put `temporary_failure` at 0.26 and `insufficient_funds` at 0.24 on
reasoning alone. NPCI's data says business declines outnumber technical ones by
roughly ten to one, and insufficient balance is the largest single business
decline cause, so the two swapped rank: `temporary_failure` 0.26 -> 0.19 and
`insufficient_funds` 0.24 -> 0.31.

Both moves make the world **harder** for the agent, not easier. The class with
the highest natural recovery becomes rarer, and the class where blanket
contacting pays off most becomes commoner. The measured effect on the headline
was to move agent-vs-naive from -Rs 6.60 (a statistical tie) to -Rs 43.57 (a
significant loss). That is the correct direction for a calibration to push a
result the author would have preferred to keep.

**Grounding.** NPCI distinguishes **Technical Declines** (infrastructure: bank or
NPCI systems unavailable, network issues) from **Business Declines** (invalid
PIN, insufficient balance, limit breaches). NPCI circular OC-149 (June 2022) sets
bank targets of TD below 1% and BD below 5% of transactions, and reported TD has
fallen to roughly 0.3-0.8%
([NPCI UPI ecosystem statistics](https://www.npci.org.in/what-we-do/upi/upi-ecosystem-statistics),
[ZeeBiz on the 0.8% TD figure](https://www.zeebiz.com/economy-infra/news-only-08-of-upi-transactions-face-technical-declines-now-npci-327217)).

Taken literally, TD/(TD+BD) implies technical causes are roughly 9-14% of all
failures. This model puts `temporary_failure` at 0.19 in the prior (15.6%
realised), which is still **higher** than the literal reading, for a stated
reason: `temporary_failure` here spans acquirer-side and gateway-side timeouts as
well as issuer-side technical declines, and a merchant-facing view includes
failures NPCI does not attribute to the issuing bank. NPCI's TD is a lower bound
on this class, not its value.

A reader who believes the true share is 9% should read the per-class results
table rather than the batch aggregate; per-class recovery rates are reported
separately for exactly this reason. The direction of the residual disagreement is
also known: a smaller `temporary_failure` share makes the world harder still.

**Deliberate deviation.** The class mix here is *not* a payments-industry mix by
transaction volume. It is a mix over a **queue of failures a recovery team would
actually work**, which over-represents structurally recoverable causes.

---

## A3 - Payment-method mix

UPI 0.62, card 0.24, netbanking 0.09, wallet 0.05.

UPI dominance reflects Indian consumer payments. **This field is descriptive
only** - no layer of the decision path branches on `method`. It exists so the
case records read like real records. Getting it wrong changes nothing.

---

## A4 - Treatment effects (odds multipliers)

Each action multiplies the **odds** of recovery, per failure class. Composing on
the odds scale rather than multiplying probabilities keeps every result in
`[0,1]` without clipping artefacts. Full table in `generator.py`.

The structure encodes payment-domain logic:

- `retry_immediate` is **below 1.0** for `insufficient_funds` (0.80),
  `invalid_method` (0.70), `repeated_failure` (0.75) and `risk_blocked` (0.85).
  Retrying instantly against an empty balance or a dead card does not merely
  fail to help - it burns one of a bounded number of attempts.
- `retry_delayed` is the strongest action for `temporary_failure` (2.30): the
  entire cause is that something was briefly unavailable.
- `method_update_request` is decisive for `invalid_method` (4.20) and close to
  inert for `temporary_failure` (0.95), where nothing is wrong with the method.
- `human_escalation` is the only action that meaningfully moves `risk_blocked`
  (3.40), because only a human can clear a risk hold.
- Per-case jitter of `exp(N(0, 0.18))` on every multiplier means no two cases in
  the same cell share an identical effect.

**Honest note.** These are structured judgements about payment mechanics, not
fitted values. Their *ordering* within a class is the defensible part; their
exact magnitudes are not.

---

## A5 - The hidden annoyance trait

Contact actions on an annoyance-prone customer have their odds multiplied by
**0.25**, applied to all four contact actions including `human_escalation`.

`P(annoyance_prone | fragile) = 0.38`, `P(annoyance_prone | not fragile) = 0.035`,
where *fragile* is the observable segment (3+ prior failures, or tenure under 30
days). Realised prevalence ~12%.

**Why probabilistic rather than a rule.** If the trait were exactly the
observable segment, the agent could identify it perfectly and the evaluation
would be circular. Because it is a coin-flip *within* the segment, the agent can
only ever learn the average effect over the segment. That irreducible gap is
deliberate: it is what makes the agent capable of being wrong.

**Why it is applied to `human_escalation` too.** An earlier version exempted
escalation. The consequence was that the *best* contact action was never
negative for any case, so the agent never faced a case where staying silent was
correct - which removes the entire point of a contact budget. The property gate
in `data/verify_world.py` caught this and failed the build. It is the clearest
example in the project of a check paying for itself.

**Grounding.** None. There is no public measurement of contact-induced churn in
Indian payment recovery. This is a modelling choice representing a real,
well-attested phenomenon (dunning fatigue, opt-outs, unsubscribes) with an
invented magnitude.

---

## A6/A7 - Gateway codes and ambiguous free text

**The codes are Razorpay's documented payment error reasons, not invented
strings.** Sources:
[UPI error codes](https://razorpay.com/docs/errors/payments/upi/),
[card error codes](https://razorpay.com/docs/errors/payments/cards/),
[full payment error list](https://razorpay.com/docs/errors/payments/list/).

An earlier version used plausible-looking inventions (`GW_TIMEOUT`,
`OTP_TIMEOUT`, `AUTH_ABANDONED`, `REPEAT_DECLINE`). They read correctly to a
non-specialist and would read as fabricated to anyone who works with the real API
daily, which for this submission is the entire audience.

**Codes are keyed by payment method**, because the real taxonomy is: `invalid_vpa`
and `vpa_resolution_failed` exist only on UPI, `card_expired` and `incorrect_cvv`
only on cards. Emitting `card_declined` on a UPI payment would be a more visible
error than inventing a code, because it is a real string used impossibly.

Three structural consequences follow, all deliberate.

**1. `repeated_failure` has no gateway code under any method.** No real gateway
emits "this is the fifth consecutive failure on this instrument" - it reports the
proximate symptom, every time. The class is reachable only from customer history.
This is strictly harder than the previous world, where an invented
`REPEAT_DECLINE` made it readable straight off the code.

*This flipped a measured design decision.* The L1 contradiction rule (4+ prior
failures against a clean symptom code) originally did **not** override the class,
because under the invented taxonomy overriding was right 44.8% of the time
against 55.2% for trusting the code. Re-measured under the real taxonomy the
override is right **69.4%** against 30.6%, so it now ships. Threshold 4 was the
best cut of 3/4/5/6/7. The reversal is caused entirely by the taxonomy becoming
real, and the reasoning for both measurements is kept in `agent/diagnosis.py`.

**2. UPI has no dedicated risk/fraud reason.** Cards get the specific
`payment_risk_check_failed`; a UPI risk block surfaces as the bare
`payment_declined`. That asymmetry is real, and it is why `payment_declined` is
diagnosed at reduced confidence.

**3. `payment_declined` also leaks (A16).** If UPI risk blocks were the *only*
cause emitting `payment_declined`, that code would be perfectly diagnostic of a
risk block in this world - an accidental giveaway of exactly the kind that makes
a synthetic evaluation circular. So 15% of UPI `insufficient_funds` and
`invalid_method` cases emit it too, which is also what real banks do when they
decline without being specific. Measured result: the modal cause of
`payment_declined` stays `risk_blocked` at **0.608**, so the code is genuinely
low-information, as a generic reason should be.

**Confidence values are measured, not chosen.** All four are fitted on the
training split only:

| Path | Cases | Measured accuracy | Constant |
|---|---:|---:|---|
| clean mapped code | 2,803 | 0.8655 | `CONF_MAPPED_CODE = 0.87` |
| generic `payment_declined` | 334 | 0.6078 | `CONF_GENERIC_CODE = 0.61` |
| contradicted -> `repeated_failure` | 271 | 0.6790 | `CONF_CONTRADICTION = 0.68` |
| keyword fallback matched | 363 | 0.6281 | `CONF_FALLBACK_KEYWORD = 0.63` |

**14.6%** of records carry the uninformative catch-all `payment_failed` plus free
text only. `payment_failed` is Razorpay's real documented general-decline reason
and is deliberately absent from `CODE_TO_CLASS`, so the ambiguous slice rides on
a real code rather than an invented `UNMAPPED` sentinel. The messages are written
in the register real gateways use - passive, vague, non-committal. Each maps to a
known true class so diagnosis accuracy stays measurable.

**Why ~15%.** High enough that the LLM path materially affects batch outcomes,
low enough that the deterministic path still carries the large majority - which is
the honest architecture. Using an LLM on a record that says `insufficient_funds`
would be waste dressed as sophistication.

**Known simplification.** Every UPI risk block emits `payment_declined`, so that
class is over-concentrated in one code relative to a real merchant's queue, where
issuer-specific NPCI decline codes (U-series, Z-series) would also appear. Those
are not in Razorpay's published merchant-facing taxonomy, so they are not
modelled rather than being guessed at.

---

## A8 - Merchant categories

Descriptive colour only. Nothing branches on it.

---

## A9 - Chronic-failer and new-customer mixtures

22% of the batch is drawn from chronically-failing instruments
(`prior_failures ~ Poisson(3.0)` instead of `Poisson(0.6)`); 22% are new
customers (`tenure ~ Uniform(0, 50)` days).

**Reasoning.** A batch of *failed payments* is not a random sample of customers.
Instruments that fail are over-represented in it precisely because they keep
failing - a selection effect, not a coincidence. Without the mixture the fragile
segment was only 8.9% of the batch, too thin for the uplift table to have data
in its cells, and too thin for targeting to be worth anything.

**Honest note.** The 22% figures are chosen to produce a fragile segment of
realistic size. They are calibration of the *world*, not of the *result* - they
were fixed before any arm was run, and the gate they satisfy
(`data/verify_world.py`) is about difficulty, not about the agent winning.

---

## A10 - Annoyance cost per customer contact: Rs 40

**This is the single most load-bearing assumption in the project.**

It represents the expected cost of one unsolicited contact, amortised across the
population: opt-out risk, churn risk, brand damage, and regulatory exposure
around unsolicited commercial communication. It is charged **on top of** the send
cost, and it is what makes the agent decline low-value contacts.

**Grounding.** None. There is no published rupee figure for this. It is an
invented number representing a real cost.

**How it is handled.** Rather than defended, it is **swept**: the sensitivity
analysis reports every arm at Rs 0, 40, 150, 400 and 900 per contact. The
honest claim the project makes is not "Rs 40 is correct" - it is "here is the
crossover point at which targeting starts to beat blanket outreach, and here is
how each arm responds as contact becomes expensive."

**What would change if it were wrong.** At Rs 0 a blanket strategy is close to
optimal and the naive arm is hard to beat, because contacting everyone costs
almost nothing against average recoverable amounts in the thousands. As the cost
rises, the naive arm keeps sending regardless while the agent withdraws
contacts. That divergence is the behaviour the system was built to exhibit, and
it is visible in the sensitivity table whichever way the headline falls.

---

## A11/A12 - Send and processing costs

| Component | Value | Grounding |
|---|---|---|
| Gateway retry attempt | Rs 2.00 | Per-attempt processing/MDR-adjacent cost. Order-of-magnitude estimate; not a quoted Razorpay fee. |
| SMS send | Rs 0.25 | Bulk transactional SMS in India runs roughly Rs 0.12-0.30 per message depending on volume and operator. |
| WhatsApp / rich message | Rs 0.85 | Meta lists India **utility** conversations at ~Rs 0.115 and **marketing** at ~Rs 0.863 per message, before BSP platform fee and 18% GST ([AiSensy rate card](https://aisensy.com/pricing), [WhatsApp API pricing India](https://whautomate.com/whatsapp-business-api-pricing-india)). Rs 0.85 takes the conservative marketing-category rate. |
| Human escalation | Rs 120.00 | Loaded cost of a few minutes of a recovery agent's time. Estimate. |

**Why the precision here does not matter.** The annoyance cost (Rs 40) exceeds
the largest send cost by roughly 47x. Getting the WhatsApp rate wrong by a
factor of two moves incremental EV by well under one rupee per case. Stating the
send costs precisely is a matter of not being sloppy, not a matter of
correctness. Rs 120 for human escalation is the one send-side number large
enough to matter, and it is deliberately set high so escalation stays scarce.

---

## A13 - Observation window: 72 hours

Recovery is counted if it occurs within 72 hours of the original failure. The
policy engine independently refuses to act on cases older than 72 hours, so the
two agree.

**Reasoning.** Long enough to capture a salary credit or a next-day retry; short
enough that attribution to the intervention remains credible. Beyond ~72h,
"recovered" increasingly means "the customer bought again", which is a different
event.

---

## A14 - Contact budget: 150 per 1,000-case batch

15 contacts per 100 failed payments. Chosen to be **genuinely binding** - the
naive arm wants roughly 5x this - so that allocation is a real constraint rather
than a decoration. A merchant would set this from their own communication policy
and send capacity.

---

## Reproducibility

Seed `8675309`, in `data/seed.txt`. `make eval` regenerates every number
reported anywhere in this repository from that seed.
