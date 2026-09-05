# AI Revenue Recovery Agent

Razorpay AI Buildathon 2026 · Track 03 · Revenue Recovery

**Not more retries. Fewer, better-targeted ones — and a number that survives
scrutiny.**

Failed-payment recovery treated as a *constrained allocation problem*. For each
failed payment the agent estimates how much revenue an intervention would add
**over doing nothing**, allocates a finite customer-contact budget to maximise
that incremental value, executes only inside a deterministic policy layer,
verifies outcomes, and proves the result against both a no-action control and a
naive retry baseline.

---

## Headline result

12,000 held-out failed payments, seed `8675309`, paired counterfactual design.
Net value is **recovered revenue minus intervention cost** — never gross.

| Arm | What it does | Net / case | Recovery | Contacts | Cost |
|---|---|---:|---:|---:|---:|
| **control** | nothing at all | ₹885.57 | 22.1% | 0 | ₹0 |
| **naive** | retry 3×, then contact everyone not opted out | ₹1,150.34 | 29.7% | 11,880 | ₹5,25,540 |
| **agent** | uplift-ranked, budget-constrained, policy-gated | ₹1,106.78 | 28.6% | **1,800** | ₹1,17,888 |

| Comparison | Net / case | 95% CI | Significant |
|---|---:|---|---|
| agent vs control | **+₹221.21** | [+₹197.01, +₹246.80] | yes |
| naive vs control | +₹264.77 | [+₹236.04, +₹294.04] | yes |
| **agent vs naive** | **−₹43.57** | **[−₹68.60, −₹19.02]** | **yes** |

### Did the agent beat the naive baseline?

**No — and the loss is statistically significant.** −₹43.57 per case, on an
interval that excludes zero.

An earlier version of this world produced a tie (−₹6.60, CI crossing zero). That
world used invented gateway error codes and an assumed failure-class mix.
Replacing both with Razorpay's documented error taxonomy and a mix calibrated
against NPCI's published decline data moved the result **against** the agent,
because business declines dominate technical ones by roughly ten to one and
`insufficient_funds` is a class where blanket contacting genuinely pays. The
calibration is documented in [`data/ASSUMPTIONS.md`](data/ASSUMPTIONS.md) (A2,
A6); the result it produced is reported here rather than the one it replaced.

The randomised between-arms design disagrees — +₹74.77, CI [−₹84.50, +₹243.84],
not significant. The paired design is far more powerful (it differences away
between-case variance, which dominates when amounts span ₹99 to ₹1,20,000), so
it is the primary and the one quoted above. Both are in `summary.json`, and the
disagreement is itself worth knowing: the loss is real but small against the
noise a merchant would actually face.

That is the honest answer and it is stated here, at the top, at the same size as
the favourable one.

**What the agent does win, decisively, is efficiency:**

| Metric | Agent | Naive | Ratio |
|---|---:|---:|---|
| Customer contacts used | 1,800 | 11,880 | **6.6× fewer** |
| Net incremental value per contact | **₹1,474.73** | ₹267.45 | **5.5×** |

The agent comes within 3.8% of an unconstrained retry bot on money recovered
while spending 15% of its customer-contact volume.

---

## Why it did not win outright

Two sweeps answer this, and they point at the same thing.

### 1. A contact is currently too cheap for targeting to pay

The annoyance cost per contact (₹40) is the single most load-bearing assumption
in the project and has no published value. So it is swept rather than defended.

| ₹ / contact | control | naive | agent | naive contacts | agent contacts | agent − naive | winner |
|---:|---:|---:|---:|---:|---:|---:|---|
| ₹0 | ₹886 | ₹1,190 | ₹1,113 | 11,880 | 1,800 | −₹77.17 | naive |
| ₹40 | ₹886 | ₹1,150 | ₹1,107 | 11,880 | 1,800 | −₹43.57 | naive |
| **₹150** | ₹886 | ₹1,041 | **₹1,090** | 11,880 | 1,800 | **+₹48.34** | **agent** |
| ₹400 | ₹886 | ₹794 | **₹1,084** | 11,880 | 1,800 | +₹290.26 | agent |
| ₹900 | ₹886 | ₹299 | **₹1,033** | 11,880 | 1,800 | +₹733.93 | agent |

**The crossover sits between ₹40 and ₹150 per contact.** When a contact costs
₹40 against an average recoverable amount in the thousands, blanket maximalism
is close to optimal — there is very little for targeting to save. As contact
becomes expensive the naive arm loses 74.9% of its net value while the agent
loses 7.2%, because it is carrying 6.6× less contact volume when the price rises.

The annoyance cost was **not** tuned until the agent won. ₹40 was fixed before
any arm was run and is the number the headline is reported at.

### 2. The agent is constrained and the naive arm is not

The agent gets 150 contacts per 1,000 cases. The naive arm has no budget at all.
Sweeping the budget separates "the targeting is no good" from "it is fighting
with one hand tied":

| Budget / 1,000 | agent contacts | agent net | naive net | agent − naive | net per contact |
|---:|---:|---:|---:|---:|---:|
| 75 | 900 | ₹1,122.24 | ₹1,150.34 | −₹28.10 | ₹3,156 |
| 150 | 1,800 | ₹1,106.78 | ₹1,150.34 | −₹43.57 | ₹1,475 |
| 300 | 3,600 | ₹1,111.71 | ₹1,150.34 | −₹38.63 | ₹754 |
| **600** | 7,200 | **₹1,167.32** | ₹1,150.34 | **+₹16.98** | ₹470 |
| 1,200 | 11,573 | **₹1,246.67** | ₹1,150.34 | **+₹96.33** | ₹374 |
| 3,000 | 11,573 | ₹1,246.67 | ₹1,150.34 | +₹96.33 | ₹374 |

**At comparable contact spend the agent wins by ₹96.33 per case.** And it
saturates: given an effectively unlimited budget it still sends only 11,573
contacts, declining 307 that the naive bot sends because their marginal value
does not clear the floor. The deficit at budget 150 is substantially a
constraint artifact rather than a targeting failure — though on this calibrated
world the agent needs roughly 4× its budget to overtake, where before it needed
3×.

### 3. Is the finding an artefact of the base rates?

The two sweeps above move the **agent** inside a fixed world. A third moves the
**world**: it perturbs the base natural-recovery rates and the treatment effects,
regenerates the population and the historical log, refits the agent on that
history, and re-runs all three arms. Batch size narrows the interval on a
simulated delta; it does nothing about that delta sitting inside a world whose
base rates were assumed. This is the only sweep that speaks to that.

| A1 natural recovery, odds scale | mean p_nat | control | naive | agent | agent − naive | winner |
|---:|---:|---:|---:|---:|---:|---|
| 0.50 | 0.159 | ₹544 | ₹762 | ₹691 | −₹71.16 | naive |
| 0.75 | 0.206 | ₹713 | ₹967 | ₹901 | −₹66.61 | naive |
| 1.00 | 0.245 | ₹846 | ₹1,119 | ₹1,022 | −₹96.90 | naive |
| 1.50 | 0.305 | ₹1,080 | ₹1,345 | ₹1,291 | −₹54.25 | naive |
| 2.00 | 0.352 | ₹1,245 | ₹1,517 | ₹1,461 | −₹55.90 | naive |

| A4 treatment strength | control | naive | agent | agent − naive | agent / contact | naive / contact | winner |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.00 (every action neutral) | ₹846 | ₹847 | ₹854 | +₹7.27 | ₹50 | ₹0 | agent |
| 0.50 | ₹846 | ₹965 | ₹915 | −₹50.19 | ₹457 | ₹112 | naive |
| 0.75 | ₹846 | ₹1,048 | ₹968 | −₹80.51 | ₹809 | ₹196 | naive |
| 1.00 | ₹846 | ₹1,119 | ₹1,022 | −₹96.90 | ₹1,174 | ₹270 | naive |
| 1.50 | ₹846 | ₹1,274 | ₹1,205 | −₹68.71 | ₹2,390 | ₹444 | naive |

**The verdict is structural, not an artefact.** The agent loses to naive on net
value in 9 of 10 perturbed worlds, across a 4× range of natural-recovery rates
and the full range of treatment effectiveness. It wins only where interventions
do nothing at all, and there it wins for the trivial reason that the naive arm's
spending is pure waste.

The efficiency finding is equally structural: the agent earns **4.1× to 5.4×**
more per contact than the naive arm in every world where interventions have any
effect. Neither result depends on the base rates being right.

*(Run it with `python -m eval.assumption_sweep`; it is also folded into
`python run.py eval` and lands in `summary.json`.)*

---

## What the third arm caught

A two-arm evaluation would have reported "+₹245 per case recovered" and stopped.
Running a naive baseline alongside caught four defects that each look like a
working system:

**1. A single EV floor.** One ₹50 minimum applied to both retries and contacts.
A retry costs ₹2; a contact carries ₹40 of annoyance on top of send cost.
The single floor suppressed hundreds of profitable retries. Two floors ship:
₹0.50 for zero-contact actions, ₹50 for contacts. 17,350 retries in the agent
arm would have been suppressed by the single floor.

**2. No sequential escalation.** The agent committed to one action type while
the naive bot retried three times *and then* contacted. The agent was doing
structurally less work, not smarter work. A standby contact candidate is now
attached at allocation time and reconsidered once retries are spent — it fires
on 714 cases.

**3. Quiet hours cancelling instead of deferring.** A 21:00–09:00 window covers
half the clock. Blocking rather than deferring silently discards recoverable
revenue for no compliance benefit. R6 now defers to the next permitted window;
862 contacts were deferred and still sent.

**4. Comparing gross recovery instead of net value.** Measured on **gross**, the
naive arm leads by ₹77.54 per case. Measured on **net**, it leads by ₹43.57.
Measuring the wrong thing overstates its advantage by 78%, because gross charges
nothing for the 11,880 contacts it sent. On the earlier uncalibrated world this
same error flipped the *sign* of the comparison; here it does not, and that is
worth stating plainly rather than keeping the more dramatic claim.

A fifth defect was caught by the generator's own property gate before anything
was built on it: `human_escalation` was exempt from the hidden annoyance trait,
which meant the *best* contact action was never negative and the agent never
faced a case where staying silent was correct.

---

## Reproducibility

```bash
python run.py all
```

Regenerates the world, verifies its difficulty gates, runs 140 tests, and
reproduces **every number in this README and in the interface** from seed
`8675309`. This run took 275.83s on Python 3.11.9. Artifacts are committed in
`eval/results/`.

`make` works too if you have it (`make all`); `run.py` exists because this was
built on Windows, where `make` is not present.

---

## Limitations

Stated here rather than buried, because the difference between a working system
and a proven one matters more than either.

1. **All evaluation is on synthetic data.** Every base rate is an assumption,
   documented in [`data/ASSUMPTIONS.md`](data/ASSUMPTIONS.md). Real validation
   needs a live merchant holdout.

2. **The world's generative process is the author's.** Holding out 12,000 cases
   controls for overfitting; it does not control for assumption error.
   Increasing the batch size narrows the interval on the *simulated* delta and
   does nothing to narrow uncertainty about whether the assumptions are right.
   At the spec's suggested 1,000-case holdout every interval crossed zero, which
   is why the batch is 12,000.

3. **Execution is entirely simulated in this run.** The Razorpay test-mode
   adapter is implemented, refuses any key that is not `rzp_test_`, and records
   real order and payment-link IDs — but no credentials were present, so
   `razorpay_test_cases` is 0 and every case carries `execution_mode:
   "simulated"`. Test mode could not have carried the full batch in any case: it
   will never simulate "the retry succeeded 40 minutes later because the
   customer's salary landed."

4. **The LLM diagnosis path ran on its fallback throughout.** No
   `ANTHROPIC_API_KEY` was present, so all 1,807 ambiguous cases were classified
   by keyword heuristic at reduced confidence (0.63 on a match, 0.30 on none)
   rather than by a model. That is the designed degradation — the batch never
   halted — and it is part of why overall diagnosis accuracy is 76.2% rather
   than higher; the other part is that `repeated_failure` no longer has a
   gateway code, by design. It also means the reliability plot has only two
   populated buckets, because the deterministic paths emit a small set of fixed
   confidence values. Both land close to the diagonal: 0.638 predicted against
   0.624 observed, and 0.870 against 0.871 — which is what one would hope for,
   since those constants were fitted on the training split.

5. **The annoyance cost is an assumption, not a measurement**, and the headline
   is sensitive to it. The sweep above is the honest response.

6. **Only failed-payment recovery is implemented.** Subscriptions, invoices and
   receivables, mandate sequencing, checkout abandonment, voice recovery and
   promise-to-pay are designed for but not built. Two shallow domains would
   score worse than one rigorous one.

---

## Architecture

Nine layers. Full detail in [`ARCHITECTURE.md`](ARCHITECTURE.md).

```
L0  SYNTHETIC WORLD      generator, hidden ground truth, historical log
          ↓  observable features only — ground truth never passes down
L1  DIAGNOSIS            rules for mapped codes; LLM for ambiguous free text
L2  UPLIFT SCORING       P(recover | action) − P(recover | no action)
L3  VALUATION            incremental EV; greedy allocation on MARGINAL gain
L4  POLICY ENGINE        deterministic, total, 8 rules → ALLOW/ESCALATE/BLOCK
L5  STATE MACHINE        enumerated transitions, bounded retries, escalation
L6  VERIFICATION         attempted ≠ succeeded ≠ confirmed
L7  AUDIT TRAIL          append-only, millisecond timestamps
L8  EVALUATION           three arms, stratified, confidence intervals
```

### The LLM boundary

**The LLM never touches money, limits, or state transitions.** It reads
unstructured gateway text and proposes a failure class. That proposal is
validated against a closed enumeration before it can affect anything — wrong
class, out-of-range confidence, or malformed JSON is discarded and the
deterministic fallback runs.

It cannot compute a financial figure, approve an action, move a counter,
trigger a transition, call a payment API, or override a policy rule. R8 rejects
any action outside the permitted enumeration; `tests/test_policy.py` covers
invented actions, case variants, and injection-shaped strings.

### The ground-truth boundary

The single mechanism preventing circular evaluation. Hidden ground truth
(`p_natural`, `p_treated`, `true_failure_class`, `annoyance_prone`) lives in its
own file that only the L0 simulator and the L8 scorer may open. The agent is
fitted **only** on a historical exploration log of 25,000 past failed payments
carrying a randomised action and an observed binary outcome — never a
probability — and it keys everything on the *predicted* failure class, not the
true one.

`tests/test_ground_truth_boundary.py` asserts this three ways: statically (no
decision module names a ground-truth field or imports the generator),
structurally (separate files), and **behaviourally** — the agent produces
byte-identical plans when `ground_truth.json` is replaced with garbage, which it
could not do if it were reading it. A companion test asserts the agent's own
`p_natural` estimate is correlated with but clearly *not equal to* the true one;
a perfect match would itself be evidence of leakage.

---

## Selected results

| | |
|---|---|
| Diagnosis accuracy | 76.2% overall, 80.9% when it commits, 5.8% abstention |
| Diagnosis paths | 10,193 rules · 1,115 keyword fallback · 692 abstained |
| Uplift correlation | +0.538 predicted vs true, over 9,400 actioned cases |
| Policy rule evaluations | 77,848 |
| Candidate actions refused by policy | R7 6,478 · R2 4,338 · R3 2,072 · R1 1,512 |
| Cases with every action refused | 2,090 |
| Quiet-hour deferrals | 862 |
| Unpermitted actions executed | **0** |
| Tests | 140 passing (72 policy, 37 state machine, 22 allocation, 9 boundary) |
| Revenue deliberately not pursued | 2,600 cases, ₹1,03,91,065 at risk |
| …of which recovered anyway | 3.7% by revenue vs 19.5% control · 5.3% by case vs 22.1% control |

That last row is the judgement claim: the cases the agent walked away from
really were the ones that were not coming back, at roughly a fifth of the
control-arm rate by revenue and under a quarter by case.

Diagnosis accuracy fell from 82.0% to 76.2% when the real taxonomy replaced the
invented one. That is the world getting harder, not the agent getting worse:
`repeated_failure` no longer has a gateway code of its own, because no real
gateway emits one, so the class is now reachable only from customer history.

The single largest of them is worth opening in the interface. `REC-1074` is a
₹1,09,688 payment, and the reason it was not pursued is:

> every action refused by policy (R2); forgoes whatsapp_nudge at
> incremental EV 10391.05

The case carried a risk score above the 0.7 block threshold. The system had a
positive-expected-value action available, priced it at ₹10,391 — the largest
single forgone EV in the batch — and declined to take it because a policy rule
said the case must not be actioned at all.
That is what "the system can give up" looks like on real money.

---

## Setup

```bash
pip install numpy pandas scipy scikit-learn pyyaml pydantic fastapi uvicorn anthropic razorpay pytest
python run.py all          # data → verify → test → eval  (~3 min)
```

To view the interface:

```bash
python run.py serve
```

```bash
cd ui && npm install && npm run dev
```

Then open <http://localhost:5173>. The API on `:8000` serves the artifacts;
`audits.json` is 4.4MB and there is no reason to ship it to a browser so a judge
can open one case.

Optional environment variables — everything degrades gracefully without them:

| Variable | Effect if absent |
|---|---|
| `ANTHROPIC_API_KEY` | LLM diagnosis falls back to a keyword heuristic at reduced confidence |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | test-mode adapter reports unavailable; the batch runs fully simulated |

### Layout

```
data/       generator, ASSUMPTIONS.md, seed, generated world + history
agent/      diagnosis, uplift, valuation, policy(+yaml), state machine,
            executors/, verification, audit
eval/       harness, calibration, sensitivity, stats, run_eval, results/
tests/      policy, state machine, allocation, ground-truth boundary
api/        read-only FastAPI over the artifacts
ui/         React + Vite, three routes
```
