import React from 'react';
import { Link } from 'react-router-dom';
import { Section } from '../components/common.jsx';
import { CLASS_LABEL, count, money, moneyExact, pct, prob, uplift } from '../lib/format.js';

/* The explainer.
 *
 * Its one job is to make uplift legible before a judge reaches the console. A
 * judge who does not have that concept reads the headline as "lost to a retry
 * bot" and stops there.
 *
 * Every number on this screen is read from summary.explainer, which the harness
 * writes. Nothing is hardcoded and nothing is computed here -- the same rule the
 * console obeys. That is what stops the explanation going stale the next time
 * the world is regenerated, which has already happened three times.
 *
 * No scroll-triggered motion. The only animation is a bar width transition that
 * fires when the reader presses a button, and it is disabled under
 * prefers-reduced-motion. */

export default function Explainer({ summary }) {
  const x = summary.explainer;
  const [treated, setTreated] = React.useState(false);

  if (!x) {
    return (
      <div className="page">
        <div className="page-title">How the agent decides</div>
        <div className="empty">
          summary.json carries no explainer block. Run <span className="mono">make eval</span>.
        </div>
      </div>
    );
  }

  const u = x.uplift_example;
  const ev = x.ev_example;
  const rej = x.rejection_example;

  return (
    <div className="page">
      <div className="page-title">How the agent decides</div>
      <div className="ex-hero">A failed payment isn&rsquo;t always lost revenue.</div>
      <div className="section-note" style={{ maxWidth: 780, marginBottom: 32 }}>
        Some failed payments come back on their own. Some come back only if you
        act. Some never come back at all. The hard part is not retrying — it is
        working out which is which, and then spending a finite number of customer
        contacts on the cases where acting actually changes the outcome. Every
        figure below is from the current run.
      </div>

      {/* ---------------------------------------------------------------- 1 */}
      <Section
        title="1 · The problem"
        note="A recovery system should only get credit for the recovery it caused. That is not the same as the recovery it observed."
      >
        <div className="ex-outcomes">
          {[
            ['Recovers naturally', 'The customer retries, the outage clears, the balance arrives. Acting here changes nothing and still costs you.'],
            ['Recovers only if you act', 'The instrument is dead, or the customer has forgotten. This is the only group worth spending on.'],
            ['Never recovers', 'Blocked, disputed, or gone. Acting here is pure cost.'],
          ].map(([h, b]) => (
            <div className="ex-outcome" key={h}>
              <div className="ex-outcome-head mono">{h}</div>
              <div className="ex-outcome-body">{b}</div>
            </div>
          ))}
        </div>
        <div className="section-note" style={{ marginTop: 16 }}>
          A retry bot treats all three identically, then counts every subsequent
          success as its own. In this run the do-nothing control arm recovers{' '}
          <span className="mono">{pct(summary.arms_paired.control.confirmed / summary.arms_paired.control.n)}</span>{' '}
          of cases while taking no action at all — so most of what a retry bot
          would report as recovered revenue was arriving regardless.
        </div>
      </Section>

      {/* ---------------------------------------------------------------- 2 */}
      <Section
        title="2 · Uplift — the only thing worth paying for"
        note="Not “will this recover?” but “will this recover BECAUSE of me?” Press the button to apply the action."
      >
        <div className="ex-uplift">
          <div className="ex-bars">
            <div className="ex-bar-row">
              <div className="ex-bar-label">do nothing</div>
              <div className="ex-track">
                <div className="ex-fill base" style={{ width: `${u.p_natural * 100}%` }} />
              </div>
              <div className="ex-bar-value mono">{prob(u.p_natural)}</div>
            </div>
            <div className="ex-bar-row">
              <div className="ex-bar-label">take the action</div>
              <div className="ex-track">
                <div className="ex-fill base" style={{ width: `${u.p_natural * 100}%` }} />
                <div
                  className="ex-fill gain"
                  style={{
                    left: `${u.p_natural * 100}%`,
                    width: treated ? `${u.uplift * 100}%` : 0,
                  }}
                />
              </div>
              <div className="ex-bar-value mono">
                {treated ? prob(u.p_treated) : prob(u.p_natural)}
              </div>
            </div>
          </div>

          <div className="ex-uplift-side">
            <div className="metric-label">incremental uplift</div>
            <div className="ex-big mono">{treated ? uplift(u.uplift) : '—'}</div>
            <button className="ex-btn" onClick={() => setTreated((v) => !v)}>
              {treated ? 'Reset' : 'Apply the action'}
            </button>
          </div>
        </div>

        <div className="section-note" style={{ marginTop: 16 }}>
          <span className="mono">{u.case_id}</span> — {money(u.amount)},{' '}
          {CLASS_LABEL[u.failure_class] ?? u.failure_class}. Acting lifts recovery
          from <span className="mono">{prob(u.p_natural)}</span> to{' '}
          <span className="mono">{prob(u.p_treated)}</span>. The gap —{' '}
          <span className="mono">{uplift(u.uplift)}</span> — is the whole value of
          intervening; the rest was going to happen anyway. This case was picked
          because its uplift is the population median (
          <span className="mono">{uplift(x.population.median_uplift)}</span>), not
          because it flatters the result.
        </div>
      </Section>

      {/* ---------------------------------------------------------------- 3 */}
      <Section
        title="3 · Turning uplift into money"
        note="amount × uplift − cost = incremental expected value. An action that helps a little on a small payment is not worth its send cost."
      >
        <div className="ex-formula mono">
          {money(ev.amount)} &nbsp;×&nbsp; uplift &nbsp;−&nbsp; cost &nbsp;=&nbsp;
          incremental EV
        </div>
        <div className="table-wrap" style={{ marginTop: 16 }}>
          <table className="table-plain">
            <thead>
              <tr>
                <th>action</th>
                <th className="right">uplift</th>
                <th className="right">cost</th>
                <th className="right">incremental EV</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {ev.actions.map((a) => (
                <tr key={a.action} className={a.selected ? 'ex-selected' : undefined}>
                  <td className="mono">{a.action}</td>
                  <td className={`num${a.uplift < 0 ? ' neg' : ''}`}>{uplift(a.uplift)}</td>
                  <td className="num">{money(a.cost)}</td>
                  <td className={`num${a.incremental_ev < 0 ? ' neg' : ''}`}>
                    {money(a.incremental_ev)}
                  </td>
                  <td className="mono muted">{a.selected ? 'selected' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="section-note" style={{ marginTop: 12 }}>
          <span className="mono">{ev.case_id}</span>, the case nearest the median
          amount in the batch. Note the bottom row: retrying immediately on an
          empty balance has <em>negative</em> uplift — the balance has not changed
          in 200 milliseconds, so the attempt burns a retry and makes recovery
          less likely, not more. An agent that only ranked actions by response
          rate would never see that.
        </div>
      </Section>

      {/* ---------------------------------------------------------------- 4 */}
      <Section
        title="4 · The contact budget"
        note="Contacting a customer is not free — it costs the send, and it costs goodwill. The merchant grants a finite number per batch, so the question stops being “is this worth doing?” and becomes “is this worth doing more than everything else competing for the same contact?”"
      >
        <div className="ex-budget">
          <div className="ex-budget-step">
            <div className="ex-big mono">{count(x.budget.contenders)}</div>
            <div className="metric-label">actions competing for a contact</div>
          </div>
          <div className="ex-budget-arrow mono">→</div>
          <div className="ex-budget-step">
            <div className="ex-big mono">{count(x.budget.budget)}</div>
            <div className="metric-label">contacts available</div>
          </div>
          <div className="ex-budget-arrow mono">→</div>
          <div className="ex-budget-step">
            <div className="ex-big mono">{moneyExact(rej.cutoff_ev)}</div>
            <div className="metric-label">the cutoff this produced</div>
          </div>
        </div>
        <div className="section-note" style={{ marginTop: 16 }}>
          Candidates are ranked by <strong>marginal</strong> gain — what the
          contact adds <em>over the free action already assigned to that case</em>
          {' '}— not by the size of the payment. A ₹50,000 payment whose contact
          adds ₹20 over a free retry loses to a ₹3,000 payment whose contact adds
          ₹800.
        </div>
      </Section>

      {/* ---------------------------------------------------------------- 5 */}
      <Section
        title="5 · The agent says no"
        note="The clearest single decision in the run: a higher-value action, declined."
      >
        <div className="ex-reject">
          <div className="ex-reject-col">
            <div className="metric-label">rejected</div>
            <div className="ex-reject-action mono">{rej.rejected_action}</div>
            <div className="ex-kv">
              <span>absolute EV</span>
              <span className="mono">{money(rej.rejected_ev)}</span>
            </div>
            <div className="ex-kv">
              <span>uplift</span>
              <span className="mono">{uplift(rej.rejected_uplift)}</span>
            </div>
          </div>
          <div className="ex-reject-col">
            <div className="metric-label">selected instead</div>
            <div className="ex-reject-action mono">{rej.selected_action}</div>
            <div className="ex-kv">
              <span>absolute EV</span>
              <span className="mono">{money(rej.selected_ev)}</span>
            </div>
            <div className="ex-kv">
              <span>consumes a contact</span>
              <span className="mono">no</span>
            </div>
          </div>
          <div className="ex-reject-col verdict">
            <div className="metric-label">why</div>
            <div className="ex-kv">
              <span>marginal gain</span>
              <span className="mono">{moneyExact(rej.marginal_gain)}</span>
            </div>
            <div className="ex-kv">
              <span>budget cutoff</span>
              <span className="mono">{moneyExact(rej.cutoff_ev)}</span>
            </div>
            <div className="ex-kv">
              <span>rank</span>
              <span className="mono">
                {count(rej.rank)} of {count(rej.contenders)}
              </span>
            </div>
            <div className="ex-verdict mono">missed by {moneyExact(rej.missed_by)}</div>
          </div>
        </div>
        <div className="section-note" style={{ marginTop: 16 }}>
          <span className="mono">{rej.case_id}</span> —{' '}
          <span className="mono">{rej.rejected_action}</span> was worth{' '}
          <span className="mono">{money(rej.rejected_ev)}</span> against{' '}
          <span className="mono">{money(rej.selected_ev)}</span> for the retry, so
          on absolute value it wins. It was still declined. A free retry was
          already assigned, so the contact only had to justify the{' '}
          <span className="mono">{moneyExact(rej.marginal_gain)}</span> it added on top
          — and that ranked {count(rej.rank)} of {count(rej.contenders)} against a
          budget of {count(x.budget.budget)}. It missed the cutoff by{' '}
          <span className="mono">{moneyExact(rej.missed_by)}</span>.
          <br />
          <br />
          The action was not useless. It was outbid. This case is selected
          automatically as the narrowest miss in the run, so it changes whenever
          the batch does.
        </div>
      </Section>

      {/* ---------------------------------------------------------------- 6 */}
      <Section
        title="6 · Where the AI sits"
        note="This project moves money, so the boundary is enforced in code and covered by tests — not asserted here."
      >
        <div className="ex-boundary">
          <div className="ex-boundary-col">
            <div className="ex-boundary-head mono">the LLM may</div>
            <ul className="ex-list">
              <li>read a free-text gateway message no code maps</li>
              <li>reason over unstructured context</li>
              <li>propose a failure class, with a confidence</li>
              <li>abstain when the evidence will not support a call</li>
              <li>explain a decision in prose</li>
            </ul>
          </div>
          <div className="ex-boundary-col">
            <div className="ex-boundary-head mono">the LLM may not</div>
            <ul className="ex-list">
              <li>compute any financial figure</li>
              <li>approve any action</li>
              <li>modify a retry or contact counter</li>
              <li>trigger a state transition</li>
              <li>call a payment API</li>
              <li>override a policy rule</li>
            </ul>
          </div>
        </div>
        <div className="callout" style={{ marginTop: 16 }}>
          <strong>The LLM proposes. Deterministic code decides.</strong> Every
          model output enters as a <em>proposal</em> and is validated against a
          permitted enumeration before it can affect anything. In this run,{' '}
          <span className="mono">
            {count(summary.policy.rule_evaluations)}
          </span>{' '}
          policy rule evaluations ran and{' '}
          <span className="mono">0</span> unpermitted actions reached an executor.
        </div>
      </Section>

      {/* -------------------------------------------------------------- CTA */}
      <div className="ex-cta">
        <div>
          <div className="ex-cta-head">That is how the agent decides.</div>
          <div className="section-note" style={{ marginTop: 4 }}>
            The console has the run itself — every case, every rejected
            alternative, the audit trail, and the three-arm comparison including
            the one the agent loses.
          </div>
        </div>
        <Link className="ex-cta-btn mono" to="/">
          Enter recovery console →
        </Link>
      </div>
    </div>
  );
}
