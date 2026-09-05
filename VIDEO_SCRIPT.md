# Demo video script — 5:00

**AI Revenue Recovery Agent · Razorpay AI Buildathon 2026 · Track 03**

## How to use this document

Each beat has two parts:

- **SCREEN** — exactly what to do in the browser. Do this *first*, then speak.
- **SAY** — read this out, word for word.

Every technical term is kept, and each is explained the first time you say it.
Sentences are short on purpose: they are easier to deliver on camera, and they
give you natural places to pause.

**767 words — about 5:05 at a normal speaking pace.**

If you are under a hard five-minute limit, take the first cut in the list at the
end (the `/case/REC-11462` shot at 1:30). That removes roughly fifteen seconds
and brings you to about **4:50**. Do not speed up to fit — the numbers are the
point, and rushing them costs more than dropping one shot.

### Before you start recording

1. Terminal one: `python run.py serve`
2. Terminal two: `cd ui && npm run dev`
3. Browser: open `http://localhost:5173/explainer` and leave it at the top
4. Open these four tabs in advance, so you never wait for a page to load:
   `/case/REC-11462` · `/case/REC-1621` · `/case/REC-4397` · `/evaluation`

### Three rules

- **Read the full numbers.** Say "two nineteen eighty-one", not "around two twenty".
- **Say the unfavourable number in a normal voice.** Do not apologise for it. It
  is the strongest part of this submission.
- **Pause between sentences.** The numbers need a moment to land.

---

# 0:00 – 0:12 · Greeting

**SCREEN** — The `/explainer` page, at the top. Nothing to click.

**SAY:**

> Hello. I'm **Srijith**, and this is my submission for **Track 3 of the Razorpay
> AI Buildathon** — the **AI Revenue Recovery Agent**.

*(Submitting as a team? Say "we", and name the team here.)*

---

# 0:12 – 0:42 · The problem, and the result

**SCREEN** — Stay on the same page. Do not scroll yet.

**SAY:**

> A failed payment is not always lost revenue.
>
> Some customers pay again on their own. Some pay only if you contact them. Some
> never pay at all.
>
> So retrying is not the difficult part. Telling those three groups apart is. When
> a payment succeeds after you act, you cannot tell whether you caused it.
>
> The result first. Against doing nothing, this agent earns **₹219.81 more per
> payment**. Against a standard retry bot, it earns **₹65.56 less**. I will show
> you both.

---

# 0:42 – 1:40 · Uplift, and one decision

**SCREEN 1** — Scroll down to the section headed **"Uplift is the only thing
worth paying for"**. Click the button labelled **"Apply the action"** as you begin
speaking. The green bar will extend.

**SAY:**

> The core idea is **uplift**.
>
> Take one failed payment. If I do nothing, it recovers **27.7 percent** of the
> time. If I act, **39.6 percent**.
>
> The difference is **11.8 percent**. That is uplift — the only portion my action
> created. The rest would have arrived without me.

**SCREEN 2** — Scroll down to the section headed **"Sometimes the best recovery
action is no action"**. The three panels should be fully visible.

**SAY:**

> Now a decision worth examining. Case `REC-11462`.
>
> An SMS was valued at **₹408.98**. A free retry at **₹220.81**. On value alone,
> the SMS is the better action.
>
> The agent declined it. Here is why.
>
> The retry costs nothing. The SMS consumes one customer contact. So the SMS only
> adds **₹188.17** on top of the retry.
>
> I have **1,800** contacts for the entire batch. This case ranked **1,801**. It
> missed by a single place. The cutoff was ₹188.21. **It missed by four paise.**

**SCREEN 3** — Switch to the `/case/REC-11462` tab. Scroll to the table headed
**"Alternatives considered"**.

**SAY:**

> Here is the same case in the operations console. The rejection reason is a
> calculation, not a label.

---

# 1:40 – 2:20 · Revenue it declined to pursue

**SCREEN 1** — Switch to the `/case/REC-1621` tab. The stop reason is near the
top of the page.

**SAY:**

> Any system can spend money. This one declines to.
>
> `REC-1621` is a **₹1,20,000** payment. The agent valued a human escalation on it
> at **₹16,863**. That is the largest single opportunity in the batch. It did not
> act.
>
> The payment had aged past seventy-two hours. Policy rule **R7** refused every
> available action.

**SCREEN 2** — Go to `/`, the run overview. Scroll to the section headed
**"Revenue deliberately not pursued"**.

**SAY:**

> Across the batch it declined **3,475** payments, worth **₹1.26 crore**.
>
> Was that correct? Of the revenue it skipped, only **4.9 percent** returned on its
> own. Across all payments, **20.2 percent** returned. It skipped the right ones.

---

# 2:20 – 2:55 · Stopping, degrading, and compliance

**SCREEN 1** — Go to `/case/REC-16014`. Show the stop reason. *(About 8 seconds.)*

**SAY:**

> Three properties the system has to demonstrate.
>
> **Stopping.** `REC-16014` retried three times and failed three times. It stopped,
> and it recorded the reason.

**SCREEN 2** — Go to `/case/REC-3980`. Show the decision trace, where the
diagnosis path and confidence are visible. *(About 12 seconds.)*

**SAY:**

> **Graceful degradation.** `REC-3980` arrived with no error code, only free text.
> There was no API key in this run, so the **LLM** could not be called. The system
> fell back to a keyword rule, then to customer history. Neither was sufficient. So
> it returned **unknown**, at **0.30 confidence**. It did not guess, and it did not
> stop the batch.

**SCREEN 3** — Go to `/evaluation`. Scroll to **"Policy and stopping"**.

**SAY:**

> **Compliance.** **70,864** policy rule evaluations. **Zero** violations.

---

# 2:55 – 3:30 · A case it got wrong

**SCREEN** — Switch to the `/case/REC-4397` tab. The decision trace shows the
confidence and the diagnosis.

**SAY:**

> Now a case the system got wrong. I would rather show you than have you find it.
>
> `REC-4397` is a **₹70,000** payment. The gateway reported insufficient funds, and
> the diagnosis layer accepted that at **94 percent confidence**. It was wrong. The
> true cause was a repeated failure. Retrying was never going to succeed.
>
> The **calibration** chart reports how often that happens at each confidence level.
>
> One thing did work. ₹70,000 exceeds the high-value threshold, so the case was
> routed to a human rather than executed automatically.

---

# 3:30 – 4:25 · The results

**SCREEN 1** — Switch to the `/evaluation` tab. Scroll to **"Three arms"** so the
comparison table is fully visible.

**SAY:**

> Three strategies, twelve thousand held-out payments. Every payment runs through
> all three, so the comparison is like for like.
>
> The **control arm** takes no action at all, and still returns **₹922** per
> payment. A standard retry bot quietly takes credit for that revenue.
>
> This agent adds **₹219.81** on top of it. The naive retry bot adds **₹285**. The
> naive bot wins on total value, and I am not hiding that.

**SCREEN 2** — Scroll to the chart headed **"Sensitivity — annoyance cost per
contact"**. **Hover your cursor over the ₹150 point** so the readout box appears,
and leave it there while you speak.

**SAY:**

> But consider the cost. This agent used **1,800** customer contacts. The naive bot
> used **11,553**.
>
> Per contact, this agent returns **₹1,465**. The naive bot returns **₹296**.
>
> Now the important part. This chart shows what happens as customer contact becomes
> more expensive. At roughly **₹150** per contact, the naive strategy collapses and
> the agent overtakes it.
>
> That cost is an assumption, so I swept it from ₹0 to ₹900 rather than defend a
> single value.

---

# 4:25 – 4:50 · Where the AI is permitted to act

**SCREEN** — Go back to `/explainer`. Scroll to the section headed **"The LLM
proposes. Deterministic code decides."** Both columns should be visible.

**SAY:**

> One architectural decision.
>
> The **LLM** reads ambiguous gateway messages. It proposes a failure class. It
> attaches a confidence score. It is permitted to abstain.
>
> That is the full extent of its authority.
>
> It calculates no financial figure. It approves no action. It cannot alter a retry
> counter or call a payment API. Every proposal is validated against a fixed list
> first.
>
> The LLM proposes. Deterministic code decides. Tests enforce that boundary.

---

# 4:50 – 5:00 · Close

**SCREEN** — Go to `/`, the run overview, so the header showing **seed 8675309**
and **batch duration 296.99s** is visible. Hold this shot until the end.

**SAY:**

> Finally, the limitations. The data is synthetic. Execution is simulated. The
> contact cost is an assumption the headline depends on.
>
> This batch runs from one seed in 296 seconds. One command reproduces every number
> I have shown. Please check it.

---

## Screen checklist

| Time | Screen | What must be visible |
|---|---|---|
| 0:00 | `/explainer` top | Title and headline |
| 0:42 | `/explainer` — "Uplift is the only thing worth paying for" | Green bar **after** clicking "Apply the action" |
| 1:05 | `/explainer` — "Sometimes the best recovery action is no action" | ₹188.17 against ₹188.21 · rank 1,801 of 4,671 |
| 1:30 | `/case/REC-11462` | "Alternatives considered" table |
| 1:40 | `/case/REC-1621` | `forgoes human_escalation at incremental EV 16863.07` |
| 2:05 | `/` overview | "Revenue deliberately not pursued" |
| 2:20 | `/case/REC-16014` | `maximum attempts reached (3)` |
| 2:30 | `/case/REC-3980` | Diagnosis path and 0.30 confidence |
| 2:50 | `/evaluation` | "Policy and stopping" |
| 2:55 | `/case/REC-4397` | 0.940 confidence, wrong class, escalated |
| 3:30 | `/evaluation` | "Three arms" table |
| 3:55 | `/evaluation` | Annoyance chart **with the hover box open** |
| 4:25 | `/explainer` | The two LLM boundary columns |
| 4:50 | `/` overview | Header: seed and batch duration |

## If you run over five minutes

Cut in this order, and no further:

1. The `/case/REC-11462` shot at 1:30 — the explainer panel already made the point
2. `REC-16014` at 2:20 — keep the degradation case and the rule count
3. The uplift bars at 0:42 — costly, but the rejection case still carries the idea

**Never cut:** the naive bot winning at 3:30, the ₹150 crossover, or the
limitations. Those three are what make this submission credible.
