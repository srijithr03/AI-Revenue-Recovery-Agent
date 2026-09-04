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
| **control** | nothing at all | ₹914.65 | 22.6% | 0 | ₹0 |
| **naive** | retry 3×, then contact everyone not opted out | ₹1,166.10 | 30.2% | 11,516 | ₹5,09,961 |
| **agent** | uplift-ranked, budget-constrained, policy-gated | ₹1,159.50 | 29.7% | **1,800** | ₹1,15,990 |

| Comparison | Net / case | 95% CI | Significant |
|---|---:|---|---|
| agent vs control | **+₹244.85** | [+₹219.76, +₹271.36] | yes |
| naive vs control | +₹251.45 | [+₹222.74, +₹280.89] | yes |
| **agent vs naive** | **−₹6.60** | **[−₹31.16, +₹18.13]** | **no** |

### Did the agent beat the naive baseline?

**No. It tied it.** The interval on the difference crosses zero, so the two are
statistically indistinguishable on net value per case. The randomised
between-arms design agrees: −₹0.07, CI [−₹149.76, +₹147.33].

That is the honest answer and it is stated here, at the top, at the same size as
the favourable one.

**What the agent does win, decisively, is efficiency:**

| Metric | Agent | Naive | Ratio |
|---|---:|---:|---|
| Customer contacts used | 1,800 | 11,516 | **6.4× fewer** |
| Net incremental value per contact | **₹1,632.31** | ₹262.01 | **6.2×** |

The agent matches an unconstrained retry bot on money recovered while spending
16% of its customer-contact budget.

---

## Why it did not win outright

Two sweeps answer this, and they point at the same thing.

### 1. A contact is currently too cheap for targeting to pay

The annoyance cost per contact (₹40) is the single most load-bearing assumption
in the project and has no published value. So it is swept rather than defended.

| ₹ / contact | control | naive | agent | naive contacts | agent contacts | agent − naive | winner |
|---:|---:|---:|---:|---:|---:|---:|---|
| ₹0 | ₹915 | ₹1,204 | ₹1,166 | 11,516 | 1,800 | −₹38.99 | naive |
| ₹40 | ₹915 | ₹1,166 | ₹1,160 | 11,516 | 1,800 | −₹6.60 | naive |
| **₹150** | ₹915 | ₹1,061 | **₹1,143** | 11,516 | 1,800 | **+₹82.46** | **agent** |
| ₹400 | ₹915 | ₹821 | **₹1,115** | 11,516 | 1,800 | +₹294.75 | agent |
| ₹900 | ₹915 | ₹341 | **₹1,063** | 11,516 | 1,800 | +₹721.74 | agent |

**The crossover sits between ₹40 and ₹150 per contact.** When a contact costs
₹40 against an average recoverable amount in the thousands, blanket maximalism
is close to optimal — there is very little for targeting to save. As contact
becomes expensive the naive arm loses 71.7% of its net value while the agent
loses 8.8%, because it is carrying 6.4× less contact volume when the price rises.

The annoyance cost was **not** tuned until the agent won. ₹40 was fixed before
any arm was run and is the number the headline is reported at.

### 2. The agent is constrained and the naive arm is not

The agent gets 150 contacts per 1,000 cases. The naive arm has no budget at all.
Sweeping the budget separates "the targeting is no good" from "it is fighting
with one hand tied":

| Budget / 1,000 | agent contacts | agent net | naive net | agent − naive | net per contact |
|---:|---:|---:|---:|---:|---:|
| 75 | 900 | ₹1,149.76 | ₹1,166.10 | −₹16.34 | ₹3,135 |
| 150 | 1,800 | ₹1,159.50 | ₹1,166.10 | −₹6.60 | ₹1,632 |
| 300 | 3,600 | ₹1,163.29 | ₹1,166.10 | −₹2.81 | ₹829 |
| **600** | 7,200 | **₹1,231.98** | ₹1,166.10 | **+₹65.88** | ₹529 |
| 1,200 | 10,396 | **₹1,299.65** | ₹1,166.10 | **+₹133.55** | ₹444 |
| 3,000 | 10,396 | ₹1,299.65 | ₹1,166.10 | +₹133.55 | ₹444 |

**At comparable contact spend the agent wins by ₹133.55 per case.** And it
saturates: given an effectively unlimited budget it still sends only 10,396
contacts, declining 1,120 that the naive bot sends because their marginal value
does not clear the floor. The deficit at budget 150 is a constraint artifact,
not a targeting failure.

---

## What the third arm caught

A two-arm evaluation would have reported "+₹245 per case recovered" and stopped.
Running a naive baseline alongside caught four defects that each look like a
working system:

**1. A single EV floor.** One ₹50 minimum applied to both retries and contacts.
A retry costs ₹2; a contact carries ₹40 of annoyance on top of send cost.
The single floor suppressed hundreds of profitable retries. Two floors ship:
₹0.50 for zero-contact actions, ₹50 for contacts. 14,617 retries in the agent
arm would have been suppressed by the single floor.

**2. No sequential escalation.** The agent committed to one action type while
the naive bot retried three times *and then* contacted. The agent was doing
structurally less work, not smarter work. A standby contact candidate is now
attached at allocation time and reconsidered once retries are spent — it fires
on 682 cases.

**3. Quiet hours cancelling instead of deferring.** A 21:00–09:00 window covers
half the clock. Blocking rather than deferring silently discards recoverable
revenue for no compliance benefit. R6 now defers to the next permitted window;
841 contacts were deferred and still sent.

**4. Comparing gross recovery instead of net value.** This one is worth a number.
Measured on **gross**, the naive arm leads by ₹39.43 per case. Measured on
**net**, it leads by ₹6.60. Measuring the wrong thing would have overstated its
lead sixfold — and gross charges nothing for the 11,516 contacts it sent.

A fifth defect was caught by the generator's own property gate before anything
was built on it: `human_escalation` was exempt from the hidden annoyance trait,
which meant the *best* contact action was never negative and the agent never
faced a case where staying silent was correct.

---

## Reproducibility

```bash
python run.py all
```

Regenerates the world, verifies its difficulty gates, runs 137 tests, and
reproduces **every number in this README and in the interface** from seed
`8675309`. This run took 145.89s on Python 3.11.9. Artifacts are committed in
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
   `ANTHROPIC_API_KEY` was present, so all 1,845 ambiguous cases were classified
   by keyword heuristic at reduced confidence (0.55 on a match, 0.30 on none)
   rather than by a model. That is the designed degradation — the batch never
   halted — and it is why overall diagnosis accuracy is 82.0% rather than
   higher. It also means the calibration plot has only two points, because the
   deterministic paths emit only two confidence values.

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
| Diagnosis accuracy | 82.0% overall, 87.1% when it commits, 5.9% abstention |
| Diagnosis paths | 10,155 rules · 1,845 fallback (LLM unavailable) |
| Uplift correlation | +0.470 predicted vs true, over 8,579 actioned cases |
| Policy rule evaluations | 71,168 |
| Candidate actions refused by policy | R7 6,262 · R2 4,974 · R3 2,220 · R1 1,578 |
| Cases with every action refused | 2,185 |
| Quiet-hour deferrals | 841 |
| Unpermitted actions executed | **0** |
| Tests | 137 passing (72 policy, 34 state machine, 22 allocation, 9 boundary) |
| Revenue deliberately not pursued | 3,421 cases, ₹1,24,92,950 at risk |
| …of which recovered anyway | 4.2% by revenue vs 20.3% control · 4.8% by case vs 22.6% control |

That last row is the judgement claim: the cases the agent walked away from
really were the ones that were not coming back, at roughly a quarter of the
control-arm rate on either measure.

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
