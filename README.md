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
| **control** | nothing at all | ₹922.19 | 23.1% | 0 | ₹0 |
| **naive** | retry 3×, then contact everyone not opted out | ₹1,207.56 | 31.3% | 11,553 | ₹5,11,726 |
| **agent** | uplift-ranked, budget-constrained, policy-gated | ₹1,142.00 | 29.8% | **1,800** | ₹1,34,853 |

| Comparison | Net / case | 95% CI | Significant |
|---|---:|---|---|
| agent vs control | **+₹219.81** | [+₹195.94, +₹244.44] | yes |
| naive vs control | +₹285.37 | [+₹255.71, +₹314.73] | yes |
| **agent vs naive** | **−₹65.56** | **[−₹93.48, −₹38.35]** | **yes** |

### Did the agent beat the naive baseline?

**No — and the loss is statistically significant.** −₹65.56 per case, on an
interval that excludes zero.

An earlier version of this world produced a tie (−₹6.60, CI crossing zero). That
world used invented gateway error codes and an assumed failure-class mix.
Replacing both with Razorpay's documented error taxonomy and a mix calibrated
against NPCI's published decline data moved the result **against** the agent,
because business declines dominate technical ones by roughly ten to one and
`insufficient_funds` is a class where blanket contacting genuinely pays. The
calibration is documented in [`data/ASSUMPTIONS.md`](data/ASSUMPTIONS.md) (A2,
A6); the result it produced is reported here rather than the one it replaced.

The randomised between-arms design now agrees: −₹61.54, CI [−₹213.05, +₹85.21],
not significant on its own but pointing the same way. It disagreed in the
previous run; it does not now. The paired design is far more powerful (it
differences away between-case variance, which dominates when amounts span ₹99 to
₹1,20,000), so it remains the primary and the one quoted above.

That is the honest answer and it is stated here, at the top, at the same size as
the favourable one.

**What the agent does win, decisively, is efficiency:**

| Metric | Agent | Naive | Ratio |
|---|---:|---:|---|
| Customer contacts used | 1,800 | 11,553 | **6.4× fewer** |
| Net incremental value per contact | **₹1,465.42** | ₹296.42 | **4.9×** |

The agent comes within 5.4% of an unconstrained retry bot on money recovered
while spending 16% of its customer-contact volume.

---

## Why it did not win outright

Two sweeps answer this, and they point at the same thing.

### 1. A contact is currently too cheap for targeting to pay

The annoyance cost per contact (₹40) is the single most load-bearing assumption
in the project and has no published value. So it is swept rather than defended.

| ₹ / contact | control | naive | agent | naive contacts | agent contacts | agent − naive | winner |
|---:|---:|---:|---:|---:|---:|---:|---|
| ₹0 | ₹922 | ₹1,246 | ₹1,148 | 11,553 | 1,800 | −₹98.07 | naive |
| ₹40 | ₹922 | ₹1,208 | ₹1,142 | 11,553 | 1,800 | −₹65.56 | naive |
| **₹150** | ₹922 | ₹1,102 | **₹1,126** | 11,553 | 1,800 | **+₹23.84** | **agent** |
| ₹400 | ₹922 | ₹861 | **₹1,104** | 11,553 | 1,800 | +₹243.34 | agent |
| ₹900 | ₹922 | ₹380 | **₹1,055** | 11,553 | 1,800 | +₹675.35 | agent |

**The crossover sits between ₹40 and ₹150 per contact.** When a contact costs
₹40 against an average recoverable amount in the thousands, blanket maximalism
is close to optimal — there is very little for targeting to save. As contact
becomes expensive the naive arm loses 69.5% of its net value while the agent
loses 8.1%, because it is carrying 6.4× less contact volume when the price rises.

The annoyance cost was **not** tuned until the agent won. ₹40 was fixed before
any arm was run and is the number the headline is reported at.

### 2. The agent is constrained and the naive arm is not

The agent gets 150 contacts per 1,000 cases. The naive arm has no budget at all.
Sweeping the budget separates "the targeting is no good" from "it is fighting
with one hand tied":

| Budget / 1,000 | agent contacts | agent net | naive net | agent − naive | net per contact |
|---:|---:|---:|---:|---:|---:|
| 75 | 900 | ₹1,132.02 | ₹1,207.56 | −₹75.55 | ₹2,798 |
| 150 | 1,800 | ₹1,142.00 | ₹1,207.56 | −₹65.56 | ₹1,465 |
| 300 | 3,600 | ₹1,136.90 | ₹1,207.56 | −₹70.66 | ₹716 |
| 600 | 7,200 | ₹1,197.64 | ₹1,207.56 | −₹9.92 | ₹459 |
| **1,200** | 10,991 | **₹1,272.66** | ₹1,207.56 | **+₹65.10** | ₹383 |
| 3,000 | 10,991 | ₹1,272.66 | ₹1,207.56 | +₹65.10 | ₹383 |

**At comparable contact spend the agent wins by ₹65.10 per case.** And it
saturates: given an effectively unlimited budget it still sends only 10,991
contacts, declining 562 that the naive bot sends because their marginal value
does not clear the floor. The deficit at budget 150 is substantially a
constraint artifact rather than a targeting failure — though the agent now needs
**8× its budget** to overtake, against 4× in the previous run. That is the
honest direction of travel: each round of making the world more realistic has
made the constrained agent's position harder, not easier.

### 3. Is the finding an artefact of the base rates?

The two sweeps above move the **agent** inside a fixed world. A third moves the
**world**: it perturbs the base natural-recovery rates and the treatment effects,
regenerates the population and the historical log, refits the agent on that
history, and re-runs all three arms. Batch size narrows the interval on a
simulated delta; it does nothing about that delta sitting inside a world whose
base rates were assumed. This is the only sweep that speaks to that.

| A1 natural recovery, odds scale | mean p_nat | control | naive | agent | agent − naive | winner |
|---:|---:|---:|---:|---:|---:|---|
| 0.50 | 0.169 | ₹633 | ₹856 | ₹796 | −₹60.60 | naive |
| 0.75 | 0.218 | ₹797 | ₹1,056 | ₹1,002 | −₹53.53 | naive |
| 1.00 | 0.258 | ₹939 | ₹1,206 | ₹1,099 | −₹107.06 | naive |
| 1.50 | 0.320 | ₹1,177 | ₹1,476 | ₹1,359 | −₹116.79 | naive |
| 2.00 | 0.367 | ₹1,338 | ₹1,665 | ₹1,531 | −₹134.85 | naive |

| A4 treatment strength | control | naive | agent | agent − naive | agent / contact | naive / contact | winner |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.00 (every action neutral) | ₹939 | ₹944 | ₹933 | −₹11.51 | −₹41 | ₹5 | naive |
| 0.50 | ₹939 | ₹1,042 | ₹1,032 | −₹9.81 | ₹619 | ₹101 | naive |
| 0.75 | ₹939 | ₹1,122 | ₹1,064 | −₹58.08 | ₹836 | ₹186 | naive |
| 1.00 | ₹939 | ₹1,206 | ₹1,099 | −₹107.06 | ₹1,068 | ₹277 | naive |
| 1.50 | ₹939 | ₹1,420 | ₹1,234 | −₹186.48 | ₹1,965 | ₹532 | naive |

**The verdict is structural, not an artefact.** The agent loses to naive on net
value in **10 of 10** perturbed worlds, across a 4× range of natural-recovery
rates and the full range of treatment effectiveness. In the previous run it won
one — the degenerate world where every action is neutral — and it no longer even
wins that.

The efficiency finding is equally structural: the agent earns **3.7× to 6.1×**
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
₹0.50 for zero-contact actions, ₹50 for contacts. 14,792 retries in the agent
arm would have been suppressed by the single floor.

**2. No sequential escalation.** The agent committed to one action type while
the naive bot retried three times *and then* contacted. The agent was doing
structurally less work, not smarter work. A standby contact candidate is now
attached at allocation time and reconsidered once retries are spent — it fires
on 705 cases.

**3. Quiet hours cancelling instead of deferring.** A 21:00–09:00 window covers
half the clock. Blocking rather than deferring silently discards recoverable
revenue for no compliance benefit. R6 now defers to the next permitted window;
821 contacts were deferred and still sent.

**4. Comparing gross recovery instead of net value.** Measured on **gross**, the
naive arm leads by ₹96.96 per case. Measured on **net**, it leads by ₹65.56.
Measuring the wrong thing overstates its advantage by 48%, because gross charges
nothing for the 11,553 contacts it sent. On the earliest uncalibrated world this
same error flipped the *sign* of the comparison; it no longer does, and the
weaker true statement replaces the stronger false one.

A fifth defect was caught by the generator's own property gate before anything
was built on it: `human_escalation` was exempt from the hidden annoyance trait,
which meant the *best* contact action was never negative and the agent never
faced a case where staying silent was correct.

---

## Is diagnosis accuracy worth improving?

Short answer, measured rather than argued: **no.**

Diagnosis accuracy is an intermediate metric. The project is scored on net value,
so an accuracy gain only counts if it moves that. Rather than assume, the harness
replaces the diagnosis layer with **ground truth**, refits the uplift table on an
oracle-diagnosed history, and re-runs all three arms. The gap is the ceiling —
the most any diagnosis work could possibly be worth.

| | real diagnosis | perfect diagnosis | difference |
|---|---:|---:|---:|
| agent net / case | ₹1,142.00 | ₹1,140.45 | **−₹1.55** |
| vs control | +₹219.81 | +₹218.27 | −₹1.54 |
| vs naive | −₹65.56 | −₹67.11 | −₹1.55 |
| net per contact | ₹1,465.42 | ₹1,455.11 | −₹10.31 |

**Going from 84.0% accurate to perfect is worth −₹1.55 per case** — nothing,
inside noise, and if anything slightly negative.

The reason is structural. The uplift table is keyed on the **predicted** class,
so it learns the right action for *"cases that look like `insufficient_funds`"*
with the mislabels included. The pipeline absorbs diagnostic error before it
reaches a decision. That is a property of the L1/L2 separation, not an accident.

This was measured **before** doing the diagnosis work, and it is the reason the
work stopped where it did. The improvements below were kept because they are
cheap and correct, not because they moved the headline — and the README says so
rather than presenting an 8-point accuracy gain as a result.

### What did improve, and why

Diagnosis went from **76.2% to 84.0%** (88.1% when it commits, abstention 4.6%).
Three changes, all measured on the training split first:

| Change | Effect |
|---|---|
| `payment_declined` read with `risk_score` | that slice 0.608 → 0.977 / 0.752 by branch |
| Keyword fallback given the case, not just the message | 0.628 → 0.683, and the contradiction rule now applies on both paths |
| Fallback consults history before abstaining | 553 abstentions left, down from 692 |

Per-class, the weak spot is where the design put it:

| class | precision | recall |
|---|---:|---:|
| temporary_failure | 0.938 | 0.928 |
| risk_blocked | 0.976 | 0.889 |
| authentication_failure | 0.958 | 0.855 |
| insufficient_funds | 0.838 | 0.902 |
| invalid_method | 0.885 | 0.787 |
| **repeated_failure** | **0.647** | **0.514** |

`repeated_failure` is weak by construction: no real gateway emits a "this is the
nth failure" reason, so it is reachable only from customer history, which is a
noisy correlate rather than a definition.

### One world defect this found

The error analysis surfaced a genuine incoherence rather than an agent weakness.
`repeated_failure` kept its full base weight at `prior_failures == 0`, so 137
training cases were labelled *"the nth consecutive failure"* with **no failure to
repeat**. They were undiagnosable by construction and capped recall at a level no
agent could reach.

The generator now forbids that. This makes the world **coherent**, not easier in
the sense that matters — no signal is added and nothing genuinely ambiguous
becomes clear — but it does raise measured accuracy, so it is reported as a world
fix and not as an agent improvement.

**How much of the gain was the world and how much was the agent?** Measured, by
running the previous diagnosis layer against the current world:

| | accuracy | attributable to |
|---|---:|---|
| old agent, old world | 0.7619 | — |
| old agent, **new world** | 0.8098 | **world fix alone: +4.79 points** |
| new agent, new world | 0.8403 | agent changes alone: +3.05 points |

**The majority of the improvement came from fixing the world, not from improving
the agent.** In the same held-fixed world the agent changes are worth **+₹2.68
per case** — real, positive, and negligible against a ₹1,142 base, which is the
same verdict the oracle ablation reaches from the other direction.

---

## Reproducibility

```bash
python run.py all
```

Regenerates the world, verifies its difficulty gates, runs 140 tests, and
reproduces **every number in this README and in the interface** from seed
`8675309`. This run took 283.52s on Python 3.11.9. Artifacts are committed in
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
   `ANTHROPIC_API_KEY` was present, so all 1,758 ambiguous cases were classified
   by keyword heuristic or customer history rather than by a model. That is the
   designed degradation — the batch never halted — and it is the single largest
   remaining source of diagnostic error: `payment_failed`, the generic code that
   routes to this path, carries **49.8%** of all diagnostic error on its own.
   Supplying a key is the largest available accuracy gain by a wide margin, and
   it needs no design change. Per the ablation above, it would not move the
   headline either.

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
| Diagnosis accuracy | 84.0% overall, 88.1% when it commits, 4.6% abstention |
| Diagnosis paths | 10,242 rules · 1,071 keyword · 134 history · 553 abstained |
| Ceiling from perfect diagnosis | **−₹1.55 / case** — accuracy is not the bottleneck |
| Uplift correlation | +0.561 predicted vs true, over 8,525 actioned cases |
| Policy rule evaluations | 70,864 |
| Candidate actions refused by policy | R7 6,464 · R2 4,320 · R3 2,012 · R1 1,530 |
| Cases with every action refused | 2,093 |
| Quiet-hour deferrals | 821 |
| Unpermitted actions executed | **0** |
| Tests | 140 passing (72 policy, 37 state machine, 22 allocation, 9 boundary) |
| Revenue deliberately not pursued | 3,475 cases, ₹1,26,50,883 at risk |
| …of which recovered anyway | 4.9% by revenue vs 20.2% control · 7.1% by case vs 23.1% control |

That last row is the judgement claim: the cases the agent walked away from
really were the ones that were not coming back, at roughly a quarter of the
control-arm rate by revenue and under a third by case.

The single largest of them is worth opening in the interface. `REC-1621` is a
₹1,20,000 payment, and the reason it was not pursued is:

> every action refused by policy (R7); forgoes human_escalation at
> incremental EV 16863.07

The case had aged past the 72-hour observation window. The system had a
positive-expected-value action available, priced it at ₹16,863 — the largest
single forgone EV in the batch — and declined to take it because a stopping rule
said the recovery was no longer attributable.
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
