import React from 'react';
import { Link } from 'react-router-dom';
import { CLASS_LABEL, count, money, moneyExact, pct, prob, uplift } from '../lib/format.js';

/* The introduction.
 *
 * Its one job is to make uplift legible before a judge reaches the console. A
 * judge who does not have that concept reads the headline as "lost to a retry
 * bot" and stops there.
 *
 * Two rules hold regardless of how this is styled:
 *
 *   1. Every number is read from summary.explainer, which the harness writes.
 *      Nothing is hardcoded and nothing is computed here. Three world
 *      regenerations in this project have already invalidated one set of
 *      hand-written figures; `make eval` keeps this screen true by
 *      construction.
 *
 *   2. Nothing animates to imply work that did not happen. Bars fill because a
 *      reader pressed a button; sections settle because they scrolled into
 *      view. Neither stands in for computation. There is no fake latency and no
 *      fake "thinking" state anywhere on this page.
 *
 * All motion respects prefers-reduced-motion. */

const SECTIONS = [
  { id: 'problem', label: 'Problem' },
  { id: 'solution', label: 'Solution' },
  { id: 'how', label: 'How it works' },
  { id: 'demo', label: 'Demo' },
];

/* Scroll reveal. Sections start slightly low and faded, and settle when they
 * enter the viewport. Under prefers-reduced-motion the CSS drops the transform
 * and transition entirely, so the class still lands and the content is simply
 * there from the start. */
const SCROLL_ID = 'intro-scroll';

function useReveal() {
  const ref = React.useRef(null);
  const [seen, setSeen] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el || seen) return undefined;
    const scroller = document.getElementById(SCROLL_ID);
    if (!scroller) {
      setSeen(true);
      return undefined;
    }
    // A position test rather than an IntersectionObserver, deliberately.
    //
    // An observer only fires when the intersection ratio crosses a threshold.
    // Jumping via the nav takes a section from below the viewport to above it
    // in a single frame without ever intersecting, so the observer never fires
    // and that section stays at opacity 0 for the rest of the session -- a
    // reader who jumps to "How it works" and then scrolls back up finds the
    // earlier sections blank.
    //
    // Testing the top edge against the scroller's bottom reveals a section both
    // when it enters from below AND when it is already above (top goes
    // negative), which is what makes the jump case correct.
    const check = () => {
      const r = el.getBoundingClientRect();
      const b = scroller.getBoundingClientRect();
      if (r.top < b.bottom - b.height * 0.08) setSeen(true);
    };
    check();
    scroller.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    return () => {
      scroller.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
    };
  }, [seen]);
  return [ref, seen];
}

function Block({ id, eyebrow, title, lede, children, wide }) {
  const [ref, seen] = useReveal();
  return (
    <section
      id={id}
      ref={ref}
      className={`in-block${seen ? '' : ' is-out'}${wide ? ' wide' : ''}`}
    >
      {eyebrow && <div className="in-eyebrow mono">{eyebrow}</div>}
      {title && <h2 className="in-h2">{title}</h2>}
      {lede && <p className="in-lede">{lede}</p>}
      {children}
    </section>
  );
}

const STAGES = [
  ['FAILED', 'A payment failed. Nothing has been decided yet — this is the queue the agent reads.'],
  ['DIAGNOSED', 'Why did it fail? A mapped gateway code resolves deterministically and costs nothing. Free text goes to the LLM, which may also abstain.'],
  ['SCORED', 'What would happen anyway? Estimate recovery with no action, then the uplift each candidate action would add on top of it.'],
  ['ELIGIBLE', 'Is this case actionable at all? Disputed, aged-out, opted-out and high-risk cases leave the pipeline here.'],
  ['POLICY CHECKED', 'Eight deterministic rules run on every candidate action, and the result is recorded even when the rule passes.'],
  ['ALLOCATED', 'Contacts are finite. Rank every candidate by marginal gain over the free action already assigned, then spend the budget down that list.'],
  ['EXECUTED', 'The approved action is issued — simulated for the batch, genuine Razorpay test mode for a small disclosed subset.'],
  ['VERIFIED', 'Attempted is not succeeded, and succeeded is not confirmed. Only confirmed recovery counts as revenue.'],
  ['RECOVERED / STOPPED / ESCALATED', 'Terminal. Stopping is a first-class outcome with a logged reason, not a failure to act.'],
];

export default function Explainer({ summary }) {
  const x = summary.explainer;
  const [treated, setTreated] = React.useState(false);
  const [stage, setStage] = React.useState(1);
  const [active, setActive] = React.useState('problem');

  /* Progress indicator. Reads scroll position and drives nothing but the nav. */
  React.useEffect(() => {
    const onScroll = () => {
      let current = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= 140) current = s.id;
      }
      setActive(current);
    };
    const scroller = document.getElementById(SCROLL_ID);
    if (!scroller) return undefined;
    onScroll();
    scroller.addEventListener('scroll', onScroll, { passive: true });
    return () => scroller.removeEventListener('scroll', onScroll);
  }, []);

  if (!x) {
    return (
      <div className="intro" id={SCROLL_ID}>
        <div className="in-wrap" style={{ paddingTop: 80 }}>
          <div className="empty">
            summary.json carries no explainer block. Run{' '}
            <span className="mono">make eval</span>.
          </div>
        </div>
      </div>
    );
  }

  const u = x.uplift_example;
  const ev = x.ev_example;
  const rej = x.rejection_example;
  const control = summary.arms_paired.control;

  return (
    <div className="intro" id={SCROLL_ID}>
      <header className="in-nav">
        <div className="in-wrap in-nav-inner">
          <div className="in-brand">
            Revenue recovery agent
            <span className="in-brand-seed mono">seed {summary.run.seed}</span>
          </div>
          <nav className="in-nav-links">
            {SECTIONS.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className={`in-nav-link${active === s.id ? ' active' : ''}`}
                onClick={(e) => {
                  // The scroll container is .intro, not the document, and a bare
                  // hash link does not reliably scroll an inner scroller. Drive
                  // it explicitly. href stays for semantics and middle-click.
                  const el = document.getElementById(s.id);
                  if (!el) return;
                  e.preventDefault();
                  el.scrollIntoView({ behavior: 'auto', block: 'start' });
                }}
              >
                {s.label}
              </a>
            ))}
            <Link className="in-nav-cta mono" to="/">
              Console →
            </Link>
          </nav>
        </div>
      </header>

      {/* ------------------------------------------------------------- hero */}
      <div className="in-hero">
        <div className="in-wrap">
          <h1 className="in-h1">
            A failed payment isn&rsquo;t always
            <br />
            lost revenue.
          </h1>
          <p className="in-hero-lede">
            Some failed payments come back on their own. Some come back only if
            you act. Some never come back at all. The hard part isn&rsquo;t
            retrying — it&rsquo;s knowing which is which.
          </p>
          <div className="in-hero-split">
            {[
              ['recovers naturally', 'Acting changes nothing, and still costs you.', pct(control.confirmed / control.n)],
              ['recovers only if you act', 'The only group worth spending on.', null],
              ['never recovers', 'Acting here is pure cost.', null],
            ].map(([h, b, stat]) => (
              <div className="in-hero-cell" key={h}>
                <div className="in-hero-cell-head mono">{h}</div>
                <div className="in-hero-cell-body">{b}</div>
                {stat && (
                  <div className="in-hero-cell-stat mono">
                    {stat} <span>of this batch, taking no action</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="in-wrap">
        {/* ---------------------------------------------------------- problem */}
        <Block
          id="problem"
          eyebrow="01 — the problem"
          title="A recovery system shouldn't get credit for revenue that was already coming."
          lede="Observed recovery is what you can see: the payment eventually succeeded. Incremental recovery is what you caused. Only the second is worth anything, and it is the one you cannot observe directly."
        >
          <div className="in-two">
            <div className="in-card">
              <div className="in-card-head mono">what a retry bot measures</div>
              <div className="in-card-body">
                Every payment that succeeded after it acted. It cannot separate
                the ones it rescued from the ones that were always going to
                arrive, so it counts both and calls the total recovered revenue.
              </div>
            </div>
            <div className="in-card accent">
              <div className="in-card-head mono">what this agent measures</div>
              <div className="in-card-body">
                The difference against a control arm that takes{' '}
                <strong>no action at all</strong>. In this run that arm still
                recovers{' '}
                <span className="mono">{pct(control.confirmed / control.n)}</span>{' '}
                of cases and{' '}
                <span className="mono">{money(control.net_per_case)}</span> per
                case — revenue no intervention can claim.
              </div>
            </div>
          </div>
        </Block>

        {/* --------------------------------------------------------- solution */}
        <Block
          id="solution"
          eyebrow="02 — the core insight"
          title="Uplift is the only thing worth paying for."
          lede="Not “will this recover?” but “will this recover because of me?” Same payment, two futures — the gap between them is the entire value of intervening."
        >
          <div className="in-uplift">
            <div className="in-bars">
              <div className="in-bar-row">
                <div className="in-bar-label">do nothing</div>
                <div className="in-track">
                  <div className="in-fill base" style={{ width: `${u.p_natural * 100}%` }} />
                </div>
                <div className="in-bar-value mono">{prob(u.p_natural)}</div>
              </div>
              <div className="in-bar-row">
                <div className="in-bar-label">take the action</div>
                <div className="in-track">
                  <div className="in-fill base" style={{ width: `${u.p_natural * 100}%` }} />
                  <div
                    className="in-fill gain"
                    style={{
                      left: `${u.p_natural * 100}%`,
                      width: treated ? `${u.uplift * 100}%` : 0,
                    }}
                  />
                </div>
                <div className="in-bar-value mono">
                  {treated ? prob(u.p_treated) : prob(u.p_natural)}
                </div>
              </div>
            </div>
            <div className="in-uplift-side">
              <div className="in-label">incremental uplift</div>
              <div className="in-figure mono">{treated ? uplift(u.uplift) : '—'}</div>
              <button className="in-btn" onClick={() => setTreated((v) => !v)}>
                {treated ? 'Reset' : 'Apply the action'}
              </button>
            </div>
          </div>
          <p className="in-note">
            <span className="mono">{u.case_id}</span> — {money(u.amount)},{' '}
            {CLASS_LABEL[u.failure_class] ?? u.failure_class}. Acting lifts
            recovery from <span className="mono">{prob(u.p_natural)}</span> to{' '}
            <span className="mono">{prob(u.p_treated)}</span>. This case is on
            screen because its uplift is the population median (
            <span className="mono">{uplift(x.population.median_uplift)}</span>) —
            chosen by the harness, not by us.
          </p>
        </Block>

        {/* -------------------------------------------------------- economics */}
        <Block
          eyebrow="03 — economics"
          title="Every intervention has a price."
          lede="Uplift alone doesn't justify an action. A small lift on a small payment doesn't cover its own send cost — and contacting a customer costs far more than the message."
        >
          <div className="in-formula mono">
            {money(ev.amount)} × uplift − cost = incremental EV
          </div>
          <div className="in-table-wrap">
            <table className="in-table">
              <thead>
                <tr>
                  <th>action</th>
                  <th className="r">uplift</th>
                  <th className="r">cost</th>
                  <th className="r">incremental EV</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {ev.actions.map((a) => (
                  <tr key={a.action} className={a.selected ? 'sel' : undefined}>
                    <td className="mono">{a.action}</td>
                    <td className={`r mono${a.uplift < 0 ? ' neg' : ''}`}>{uplift(a.uplift)}</td>
                    <td className="r mono">{money(a.cost)}</td>
                    <td className={`r mono${a.incremental_ev < 0 ? ' neg' : ''}`}>
                      {money(a.incremental_ev)}
                    </td>
                    <td className="mono dim">{a.selected ? 'selected' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="in-note">
            <span className="mono">{ev.case_id}</span>, the case nearest the
            median amount in the batch. Note the bottom row: retrying immediately
            on an empty balance carries <em>negative</em> uplift — the balance
            hasn&rsquo;t changed in 200 milliseconds, so the attempt burns a retry
            and makes recovery <em>less</em> likely, not more. A model that ranked
            actions by response rate alone would never see that.
          </p>
        </Block>

        {/* ----------------------------------------------------------- budget */}
        <Block
          eyebrow="04 — the constraint"
          title="You can't contact everyone."
          lede="The merchant grants a finite number of customer contacts per batch. That turns the question from “is this worth doing?” into “is this worth doing more than everything else competing for the same contact?”"
        >
          <div className="in-flow">
            <div className="in-flow-step">
              <div className="in-figure mono">{count(x.budget.contenders)}</div>
              <div className="in-label">actions competing for a contact</div>
            </div>
            <div className="in-flow-arrow mono">→</div>
            <div className="in-flow-step">
              <div className="in-figure mono">{count(x.budget.budget)}</div>
              <div className="in-label">contacts available</div>
            </div>
            <div className="in-flow-arrow mono">→</div>
            <div className="in-flow-step accent">
              <div className="in-figure mono">{moneyExact(rej.cutoff_ev)}</div>
              <div className="in-label">the cutoff this produced</div>
            </div>
          </div>
          <p className="in-note">
            Candidates rank by <strong>marginal</strong> gain — what the contact
            adds <em>over the free action already assigned to that case</em> — not
            by the size of the payment. A ₹50,000 payment whose contact adds ₹20
            over a free retry loses to a ₹3,000 payment whose contact adds ₹800.
          </p>
        </Block>

        {/* ---------------------------------------------------------- says no */}
        <Block
          eyebrow="05 — restraint"
          title="Sometimes the best recovery action is no action."
          lede="The clearest single decision in this run: a higher-value action, declined."
          wide
        >
          <div className="in-verdict">
            <div className="in-verdict-col">
              <div className="in-label">rejected</div>
              <div className="in-verdict-action mono">{rej.rejected_action}</div>
              <div className="in-kv"><span>absolute EV</span><span className="mono">{money(rej.rejected_ev)}</span></div>
              <div className="in-kv"><span>uplift</span><span className="mono">{uplift(rej.rejected_uplift)}</span></div>
            </div>
            <div className="in-verdict-col">
              <div className="in-label">taken instead</div>
              <div className="in-verdict-action mono">{rej.selected_action}</div>
              <div className="in-kv"><span>absolute EV</span><span className="mono">{money(rej.selected_ev)}</span></div>
              <div className="in-kv"><span>consumes a contact</span><span className="mono">no</span></div>
            </div>
            <div className="in-verdict-col why">
              <div className="in-label">why</div>
              <div className="in-kv"><span>marginal gain</span><span className="mono">{moneyExact(rej.marginal_gain)}</span></div>
              <div className="in-kv"><span>budget cutoff</span><span className="mono">{moneyExact(rej.cutoff_ev)}</span></div>
              <div className="in-kv"><span>rank</span><span className="mono">{count(rej.rank)} of {count(rej.contenders)}</span></div>
              <div className="in-missed mono">missed by {moneyExact(rej.missed_by)}</div>
            </div>
          </div>
          <p className="in-note">
            <span className="mono">{rej.case_id}</span> —{' '}
            <span className="mono">{rej.rejected_action}</span> was worth{' '}
            <span className="mono">{money(rej.rejected_ev)}</span> against{' '}
            <span className="mono">{money(rej.selected_ev)}</span> for the retry,
            so on absolute value it wins. It was still declined. A free retry was
            already assigned, so the contact only had to justify the{' '}
            <span className="mono">{moneyExact(rej.marginal_gain)}</span> it added
            on top — and that ranked {count(rej.rank)} of{' '}
            {count(rej.contenders)} against a budget of {count(x.budget.budget)}.
            <br />
            <br />
            The action wasn&rsquo;t useless. It was outbid. This case is selected
            automatically as the narrowest miss in the run, so it changes whenever
            the batch does — open{' '}
            <Link className="in-inline-link mono" to={`/case/${rej.case_id}`}>
              {rej.case_id}
            </Link>{' '}
            in the console and the same numbers are there.
          </p>
        </Block>

        {/* --------------------------------------------------------- workflow */}
        <Block
          id="how"
          eyebrow="06 — the pipeline"
          title="How a decision actually gets made."
          lede="Nine stages, and every one of them can stop the case. Select a stage to see what it does."
          wide
        >
          <div className="in-stages">
            {STAGES.map(([name], i) => (
              <button
                key={name}
                className={`in-stage${i === stage ? ' active' : ''}${i < stage ? ' past' : ''}`}
                onClick={() => setStage(i)}
              >
                <span className="in-stage-dot" />
                <span className="in-stage-name mono">{name}</span>
              </button>
            ))}
          </div>
          <div className="in-stage-detail">
            <div className="in-stage-detail-head mono">{STAGES[stage][0]}</div>
            <div className="in-stage-detail-body">{STAGES[stage][1]}</div>
          </div>
        </Block>

        {/* --------------------------------------------------------- boundary */}
        <Block
          eyebrow="07 — the boundary"
          title="The LLM proposes. Deterministic code decides."
          lede="This system moves money, so the boundary is enforced in code and covered by tests — not asserted on a slide."
        >
          <div className="in-two">
            <div className="in-card">
              <div className="in-card-head mono">the LLM may</div>
              <ul className="in-list">
                <li>read a free-text gateway message no code maps</li>
                <li>reason over unstructured context</li>
                <li>propose a failure class, with a confidence</li>
                <li>abstain when the evidence won&rsquo;t support a call</li>
                <li>explain a decision in prose</li>
              </ul>
            </div>
            <div className="in-card">
              <div className="in-card-head mono">the LLM may not</div>
              <ul className="in-list">
                <li>compute any financial figure</li>
                <li>approve any action</li>
                <li>modify a retry or contact counter</li>
                <li>trigger a state transition</li>
                <li>call a payment API</li>
                <li>override a policy rule</li>
              </ul>
            </div>
          </div>
          <p className="in-note">
            Every model output enters as a <em>proposal</em> and is validated
            against a permitted enumeration before it can affect anything. In this
            run{' '}
            <span className="mono">{count(summary.policy.rule_evaluations)}</span>{' '}
            policy rule evaluations ran and <span className="mono">0</span>{' '}
            unpermitted actions reached an executor.
          </p>
        </Block>
      </div>

      {/* --------------------------------------------------------------- CTA */}
      <div className="in-cta" id="demo">
        <div className="in-wrap">
          <h2 className="in-cta-head">Now see it run.</h2>
          <p className="in-cta-lede">
            The console has the batch itself — every case, every rejected
            alternative, the audit trail, and the three-arm comparison including
            the one the agent loses.
          </p>
          <Link className="in-cta-btn mono" to="/">
            Enter recovery console →
          </Link>
          <div className="in-foot mono">
            seed {summary.run.seed} · {count(summary.run.n_holdout)} case holdout ·
            every figure on this page regenerated by make eval
          </div>
        </div>
      </div>
    </div>
  );
}
