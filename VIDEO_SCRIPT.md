# Demo video script — 5:00

**AI Revenue Recovery Agent · Razorpay AI Buildathon 2026 · Track 03**

Narration is word-for-word. **ON SCREEN** tells you what to show and when.

Written to be **spoken, not read**. Short sentences, one idea each. All the
technical terms are still here — uplift, control arm, expected value, policy
rule, calibration, LLM — but each one is explained the first time you say it.

**765 words. That is about 5:05 at a normal speaking pace.**

Average sentence is 6 words. Nothing is longer than 18. That is deliberate —
short sentences are much easier to deliver naturally on camera.

Three rules while recording:

- **Run it live.** Do not talk over screenshots. The terminal and the chart
  hover are the two things a fake demo cannot do.
- **Say the full numbers.** "Two nineteen eighty-one", not "around two twenty".
- **Say the bad number in a normal voice.** Do not apologise for it. It is the
  strongest part of this submission, not the weakest.

Before recording: `python run.py serve` in terminal one, `cd ui && npm run dev`
in terminal two, browser on `localhost:5173`, and a third terminal empty and
ready.

---

## 0:00 – 0:12 · Greeting

> **ON SCREEN** — `/explainer`, already loaded. Camera or voice only, both fine.
> Keep it short. This is the only part that is not evidence.

Hi, I'm **Srijith**. This is my submission for **Track 3 of the Razorpay AI
Buildathon** — the **AI Revenue Recovery Agent**.

> **Change this if needed:** submitting as a team? Say "we" and name the team.

---

## 0:12 – 0:38 · The problem, and my answer

> **ON SCREEN** — stay on the hero. Do not scroll yet.

A failed payment is not always lost money.

Some customers pay again on their own. Some pay only if you contact them. Some
never pay at all.

So retrying is not the hard part. The hard part is knowing which is which. When
a payment succeeds after you act, you cannot tell if you caused it.

Here is my result first. Against doing nothing, my agent earns **₹219.81 more
per payment**. Against a normal retry bot, it earns **₹65.56 less**.

---

## 0:38 – 1:02 · Proof that it runs

> **ON SCREEN** — cut to terminal. Type it live. Let it scroll. Cut at ~1:02.

```bash
python run.py all
```

One command runs everything. It creates sixteen thousand test payments. It
checks the test data is hard enough. It runs a hundred and forty tests. Then it
compares three strategies on twelve thousand payments.

It takes **296 seconds**. Every number I show you comes from this command.

---

## 1:02 – 1:58 · The main idea, and one decision

> **ON SCREEN** — `/explainer` §02. Press **Apply the action** as you talk.

The main idea is called **uplift**.

Take one failed payment. If I do nothing, it recovers **27.7%** of the time. If I
act, it recovers **39.6%** of the time.

The difference is **11.8%**. That is uplift. That is the only part my action
created. The rest was going to happen without me.

> **ON SCREEN** — scroll to §05, "The agent says no".

Now watch this case. `REC-11462`.

Sending an SMS was worth **₹408.98**. A free retry was worth **₹220.81**. So the
SMS looks better.

The agent said no. Here is why.

The retry is free. The SMS uses one customer contact. So the SMS only adds
**₹188.17** of extra value on top.

I only have **1,800** contacts for the whole batch. This case ranked **1,801**.
It missed by one place. The cutoff was ₹188.21. **It missed by four paise.**

> **ON SCREEN** — click through to `/case/REC-11462`.

Same case in the console. The reason is a calculation, not a label.

---

## 1:58 – 2:38 · Money it refused to chase

> **ON SCREEN** — `/case/REC-1621`, then `/` overview.

Any system can spend money. This one refuses.

`REC-1621` is a **₹1,20,000** payment. The agent found an action worth
**₹16,863**. That is the biggest opportunity in the whole batch. It did not act.

Why? The payment was more than 72 hours old. Policy rule **R7** blocked every
action.

Across the batch it skipped **3,475** payments, worth **₹1.26 crore**.

Was that correct? Of the money it skipped, only **4.9%** came back on its own.
Across all payments, **20.2%** came back. So it skipped the right ones.

---

## 2:38 – 3:08 · Stopping, failing safely, and rules

> **ON SCREEN** — `/case/REC-16014`, `/case/REC-3980`, then `/evaluation`
> "Policy and stopping". About ten seconds each.

Three quick things.

**Stopping.** `REC-16014` retried three times. All three failed. It stopped, and
it logged the reason.

**Failure handling.** `REC-3980` had no error code, only text. I had no API key
in this run, so the **LLM could not run**. The system used a keyword rule, then
customer history. Neither was enough. So it answered **unknown**, at **0.30
confidence**. It did not guess, and it did not crash.

**Rules.** **70,864** policy checks. **Zero** violations.

---

## 3:08 – 3:40 · A mistake it made

> **ON SCREEN** — `/case/REC-4397`.

Now a mistake. I would rather show you myself.

`REC-4397` is a **₹70,000** payment. The gateway said insufficient funds. My
system believed it, at **94% confidence**. That was wrong. The real cause was
repeated failure. Retrying was never going to work.

My **calibration** chart shows how often this happens at each confidence level.

One thing did work. ₹70,000 is above my high-value limit. So this case went to a
human for approval, instead of running automatically.

---

## 3:40 – 4:32 · The results, honestly

> **ON SCREEN** — `/evaluation`, three-arm section.

Three strategies. Twelve thousand payments. Every payment goes through all three,
so the comparison is fair.

**Control** does nothing at all. It still earns **₹922** per payment. A normal
retry bot takes credit for that money.

My agent adds **₹219.81** on top of that. The naive bot adds **₹285**. So the
naive bot wins on total value. I am not hiding that.

> **ON SCREEN** — scroll to the annoyance chart. **Hover the ₹150 point.**

But look at the cost. My agent used **1,800** customer contacts. The naive bot
used **11,553**.

Per contact, my agent earns **₹1,465**. The naive bot earns **₹296**.

Now the important part. This chart shows what happens when contacting a customer
gets expensive. At about **₹150** per contact, the naive bot collapses, and my
agent overtakes it.

That cost is an assumption. So I tested it from ₹0 to ₹900.

---

## 4:32 – 4:58 · Where the AI is allowed to work

> **ON SCREEN** — `/explainer` §07, the two columns.

One design decision.

The **LLM** reads unclear error messages. It suggests a cause. It gives a
confidence score. It is allowed to say it does not know.

That is all it does.

It never calculates money. It never approves an action. It never changes a retry
counter. It never calls a payment API. Every LLM answer is checked against a
fixed list first.

The LLM suggests. Normal code decides. Tests enforce that.

---

## 4:58 – 5:18 · Close

> **ON SCREEN** — `/evaluation`, Limitations. Hold to the end.

My limitations, honestly.

The data is synthetic. The execution is simulated. The contact cost is an
assumption, and my result depends on it.

And in all **ten** alternative test worlds, the naive bot won on total value.
What held in all ten was efficiency per contact.

Seed **8675309**. One command reproduces everything. Please check it.

---

## Shot list

| # | Screen | What must be visible |
|---|---|---|
| 1 | `/explainer` hero | greeting, then the headline |
| 2 | terminal | `python run.py all` running live |
| 3 | `/explainer` §02 | uplift bars **after** the button press |
| 4 | `/explainer` §05 | ₹188.17 vs ₹188.21 · rank 1,801 of 4,671 |
| 5 | `/case/REC-11462` | the calculated rejection reason |
| 6 | `/case/REC-1621` | `forgoes human_escalation at incremental EV 16863.07` |
| 7 | `/` overview | "Revenue deliberately not pursued" |
| 8 | `/case/REC-16014` | `maximum attempts reached (3)` |
| 9 | `/case/REC-3980` | `fallback_none` · 0.30 confidence · no-key reason |
| 10 | `/case/REC-4397` | 0.940 confidence · wrong class · escalated |
| 11 | `/evaluation` | three-arm table |
| 12 | `/evaluation` | annoyance chart **with the hover box open** |
| 13 | `/explainer` §07 | the two columns |
| 14 | `/evaluation` | Limitations |

## If you run out of time

Cut in this order, and no further:

1. The `/case/REC-11462` console shot at 1:58 — §05 already made the point
2. `REC-16014` at 2:38 — keep the failure handling and the rule count
3. The uplift bars at 1:02 — painful, but the rejection case carries the idea

**Never cut:** the naive bot winning at 3:40, the ₹150 crossover, or the
limitations. Those three are why this submission is believable. Cutting them to
save time makes it an ordinary demo.
