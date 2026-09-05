# Demo video script — 5:00

**AI Revenue Recovery Agent · Razorpay AI Buildathon 2026 · Track 03**

Narration is word-for-word. **ON SCREEN** tells you what to cut to and when.

**729 spoken words.** That is **4:52** at a normal 150 words/minute and **5:12**
if you slow down for the figures. The timecodes below assume the slower pace, so
if you are under a hard 5:00 limit, read at normal speed and you have twenty
seconds of headroom — or take the first cut in the overrun list. Do not speed up
to fit; the numbers are the point and rushing them is worse than dropping a beat.

Three rules while recording:

- **Run it live.** Don't narrate over stills. The terminal beat and the chart
  hover are the two things a mockup cannot fake.
- **Read numbers off the screen, unrounded.** "Two-nineteen eighty-one", not
  "about two-twenty".
- **Don't apologise for the loss.** Deliver the naive comparison in the same
  tone as the win. It is the strongest thing in the pitch, not the weakest.

Before recording: `python run.py serve` in one terminal, `cd ui && npm run dev`
in another, browser on `localhost:5173`, and a third terminal cleared in the
project root.

---

## 0:00 – 0:25 · Lead with the answer

> **ON SCREEN** — `/explainer`, the hero. Don't scroll.

A failed payment isn't always lost revenue. The hard part isn't retrying — it's
that *revenue recovered* isn't observable. You can see a payment succeed after
you intervened. You can't see whether it would have anyway.

So, the headline first. Against a control arm that does nothing, this agent adds
₹219.81 per case. Against an unconstrained retry bot, it **loses** by ₹65.56.
The second number is the more interesting one.

---

## 0:25 – 0:50 · Prove it runs

> **ON SCREEN** — cut to terminal. Type it live, let it scroll, cut away ~0:50.

```bash
python run.py all
```

That's the whole pipeline from one seed. Sixteen thousand synthetic failed
payments, the difficulty gates that verify the world is actually hard, a hundred
and forty tests, then three arms evaluated on a twelve-thousand-case holdout.

End to end, 296 seconds. Every number I'm about to show comes out of this one
command.

---

## 0:50 – 1:45 · One decision, end to end

> **ON SCREEN** — `/explainer` §02. Press **Apply the action** as you speak.

Same failed payment, two futures. Do nothing, it recovers with probability
0.277. Act, and it's 0.396. That gap — **+0.118** — is the only thing worth
paying for. The rest was arriving regardless.

> **ON SCREEN** — scroll to §05, "The agent says no".

Now the decision that makes this an agent and not a scheduler. `REC-11462`. An
SMS payment link scored ₹408.98. The retry actually taken scored ₹220.81. On
absolute value, the SMS wins.

It was declined. A free retry was already assigned, so the contact only had to
justify the **₹188.17** it added on top — and that ranked **1,801 out of 4,671**
against a budget of 1,800.

It missed the cutoff by four paise.

> **ON SCREEN** — click through to `/case/REC-11462`.

Same case in the console, with the reason the system computed — rank, cutoff,
marginal gain. Not a label. Arithmetic.

---

## 1:45 – 2:25 · What it deliberately walked away from

> **ON SCREEN** — `/case/REC-1621`.

Restraint is easy to claim, so here's the largest thing it refused. `REC-1621`,
**₹1,20,000**. The system scored a human escalation on it at **₹16,863** of
incremental expected value — the largest forgone opportunity in the batch — and
did not act. The case had aged past the 72-hour window; rule R7 refused
everything.

> **ON SCREEN** — `/` overview, "Revenue deliberately not pursued".

Across the batch: 3,475 cases, ₹1.26 crore at risk, left alone. And the check
that this was right — of the revenue it skipped, **4.9%** came back on its own,
against **20.2%** across the control arm. It skipped the cases that genuinely
weren't coming back.

---

## 2:25 – 2:55 · Stopping, degrading, complying

> **ON SCREEN** — `/case/REC-16014`, then `/case/REC-3980`, then `/evaluation`
> "Policy and stopping". Move fast, ~10 seconds each.

Stopping. `REC-16014` retried three times, failed, and stopped — reason logged,
not inferred.

Degradation. `REC-3980` had free text and no usable code. No API key in this
run, so the LLM path fell back to a keyword heuristic, then to customer history,
and when neither supported a call it **abstained** at 0.30 confidence. The batch
never halted.

Compliance. **70,864** policy rule evaluations. **Zero** violations.

---

## 2:55 – 3:30 · What it got wrong

> **ON SCREEN** — `/case/REC-4397`.

Here's one it got wrong. I'd rather name it than have you find it.

`REC-4397`, ₹70,000. The gateway said insufficient funds and the diagnosis layer
believed it at **94% confidence**. The true cause was a repeated failure on a
chronically failing instrument — retrying was never going to work.

That's a wrong prediction, and the calibration plot shows how often that happens
at each confidence level. What it got right was routing: at ₹70,000 the case
crossed the high-value threshold and went for human approval instead of
executing automatically.

---

## 3:30 – 4:20 · The number, honestly

> **ON SCREEN** — `/evaluation`, three-arm section.

Three arms, twelve thousand held-out cases, paired so every case runs through
all three on the same latent draw.

Control does nothing and still returns **₹922** per case — the number a retry bot
quietly takes credit for.

The agent adds ₹219.81 over it. The naive bot adds ₹285. **The naive bot wins,
and it wins significantly.**

> **ON SCREEN** — scroll to the annoyance chart. **Hover the ₹150 point.**

But look what it costs. The agent spends **1,800** contacts. The naive bot spends
**11,553** to buy that ₹65 lead. Per contact: **₹1,465** against **₹296**.

And here's the crossover. Once a contact costs more than about ₹150, the naive
strategy collapses and the agent overtakes it. That assumption is what the
comparison turns on — so it's swept ₹0 to ₹900 rather than defended.

---

## 4:20 – 4:48 · Where the AI is allowed to act

> **ON SCREEN** — `/explainer` §07, the two boundary columns.

One architectural decision. The model reads ambiguous gateway text, proposes a
failure class with a confidence, and may abstain.

It computes no financial figure, approves no action, and cannot move a counter,
trigger a transition, or call a payment API. Every output enters as a proposal
and is validated against a closed enumeration first.

The LLM proposes. Deterministic code decides — and that boundary is covered by
tests.

---

## 4:48 – 5:08 · Close on something falsifiable

> **ON SCREEN** — `/evaluation`, Limitations. Hold it to the end.

Limitations, plainly. Synthetic data. Simulated execution. The annoyance cost is
an assumption the headline is sensitive to. And the agent loses to naive in **ten
out of ten** perturbed worlds — what survives all ten is the efficiency.

Seed 8675309. One command reproduces every number here. Please check it.

---

## Shot list

| # | Screen | What must be visible |
|---|---|---|
| 1 | `/explainer` hero | the headline claim |
| 2 | terminal | `python run.py all` scrolling live |
| 3 | `/explainer` §02 | uplift bars **after** the button press |
| 4 | `/explainer` §05 | ₹188.17 vs ₹188.21 · rank 1,801 of 4,671 |
| 5 | `/case/REC-11462` | computed rejection reason in the alternatives table |
| 6 | `/case/REC-1621` | `forgoes human_escalation at incremental EV 16863.07` |
| 7 | `/` overview | "Revenue deliberately not pursued" |
| 8 | `/case/REC-16014` | `maximum attempts reached (3)` |
| 9 | `/case/REC-3980` | `fallback_none` · confidence 0.30 · no-key reason |
| 10 | `/case/REC-4397` | confidence 0.940 · wrong class · escalated |
| 11 | `/evaluation` | three-arm table |
| 12 | `/evaluation` | annoyance chart **with the hover readout open** |
| 13 | `/explainer` §07 | the two boundary columns |
| 14 | `/evaluation` | Limitations |

## If you overrun

Cut in this order, and no further:

1. The `/case/REC-11462` console cut at 1:45 — §05 already made the point
2. `REC-16014` at 2:25 — keep the fallback and the policy count
3. The uplift bars at 0:50 — painful, but the rejection beat carries the idea

**Never cut:** the naive loss at 3:30, the crossover, or the limitations. Those
three are why this is credible. Dropping them to save time turns a strong honest
pitch into an ordinary one.
