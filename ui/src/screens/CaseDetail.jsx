import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { fetchCase } from '../lib/api.js';
import {
  CLASS_LABEL, PATH_LABEL, REJECTION_LABEL, clock, count, hour, money,
  moneyExact, pct, prob, rank, uplift,
} from '../lib/format.js';
import {
  Chip, ErrorState, Loading, Metric, MetricRow, Section, StateChip,
} from '../components/common.jsx';

const STAGES = ['Failed', 'Diagnosed', 'Scored', 'Policy', 'Executed', 'Verified', 'Final'];

export default function CaseDetail({ summary }) {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    fetchCase(id).then(setData).catch(setError);
  }, [id]);

  if (error) return <div className="page"><ErrorState error={error} /></div>;
  if (!data) return <div className="page"><Loading what={id} /></div>;

  const { case: c, alternatives, audit } = data;
  const bucket = findBucket(summary.diagnosis.reliability, c.diag_confidence);
  const events = new Set(audit.map((e) => e.event));

  const reached = {
    Failed: true,
    Diagnosed: events.has('DIAGNOSED'),
    Scored: events.has('SCORED'),
    Policy: events.has('POLICY_CHECKED') || events.has('INELIGIBLE'),
    Executed: events.has('EXECUTING'),
    Verified: events.has('OUTCOME_CHECK') || events.has('RECOVERED'),
    Final: true,
  };

  return (
    <div className="page">
      {/* Back link preserves whatever filter and sort the table was in. */}
      <Link to="/" className="back">← Back to run overview</Link>

      <div className="badges">
        <h1 className="page-title mono" style={{ margin: 0 }}>{c.case_id}</h1>
        <Chip>{c.arm}</Chip>
        <Chip>{c.execution_mode}</Chip>
        <StateChip state={c.state} />
        {c.confirmed && <Chip tone="recovered">revenue confirmed</Chip>}
        {!c.diagnosis_correct && <Chip tone="blocked">diagnosis wrong</Chip>}
      </div>

      <Section>
        <MetricRow>
          <Metric label="at risk" value={moneyExact(c.amount)} sub={`${c.method} · ${c.merchant_category}`} />
          <Metric
            label="P(recover | act)"
            value={prob(c.p_treated)}
            sub={c.action === 'no_action' ? 'no action selected' : c.action}
          />
          <Metric label="P(recover | no action)" value={prob(c.p_natural)} sub="agent estimate" />
          <Metric
            label="incremental EV"
            value={money(c.incremental_ev)}
            sub={`uplift ${uplift(c.uplift)}`}
          />
        </MetricRow>
      </Section>

      <Section title="Decision trace">
        <table className="kv">
          <tbody>
            <tr>
              <td>gateway signal</td>
              <td className="mono">
                {c.gateway_code}
                {c.gateway_message && (
                  <div className="muted" style={{ marginTop: 4, whiteSpace: 'normal' }}>
                    “{c.gateway_message}”
                  </div>
                )}
              </td>
            </tr>
            <tr>
              <td>diagnosis</td>
              <td>
                <span className="mono">{c.failure_class}</span>{' '}
                <span className="muted">via {PATH_LABEL[c.diag_path] || c.diag_path}</span>
                {!c.diagnosis_correct && (
                  <div className="neg mono" style={{ marginTop: 4 }}>
                    true class was {c.true_failure_class}
                  </div>
                )}
              </td>
            </tr>
            <tr>
              <td>confidence</td>
              <td className="mono">
                {prob(c.diag_confidence)}
                {bucket && (
                  <span className="muted">
                    {' '}· {pct(bucket.observed_accuracy)} observed accuracy in this bucket
                    ({count(bucket.n)} cases)
                  </span>
                )}
              </td>
            </tr>
            <tr>
              <td>signals used</td>
              <td>
                <ul className="plain mono" style={{ fontSize: 12 }}>
                  {c.diag_signals.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
                {c.diag_llm_error && (
                  <div className="muted mono" style={{ fontSize: 12, marginTop: 4 }}>
                    llm unavailable: {c.diag_llm_error} — fell back at reduced confidence
                  </div>
                )}
              </td>
            </tr>
            <tr>
              <td>customer</td>
              <td className="mono">
                segment {c.segment} · {c.prior_success} prior successes ·{' '}
                {c.prior_failures} prior failures · {count(c.tenure_days)} days tenure
              </td>
            </tr>
            <tr>
              <td>failed at</td>
              <td className="mono">
                {hour(c.hour)} IST · {c.age_hours.toFixed(1)}h ago · risk {prob(c.risk_score)}
                {c.opted_out && <span className="neg"> · opted out</span>}
                {c.disputed && <span className="neg"> · disputed</span>}
              </td>
            </tr>
            <tr>
              <td>contact budget position</td>
              <td className="mono">
                {c.budget_rank
                  ? <>
                      rank {rank(c.budget_rank, c.budget_contenders)} contenders
                      {c.won_contact
                        ? ' — won a contact slot'
                        : <> — below the cutoff at {money(c.budget_cutoff_ev)}</>}
                    </>
                  : <span className="muted">not a contact contender</span>}
              </td>
            </tr>
            <tr>
              <td>selected action</td>
              <td className="mono">
                {c.action}
                {c.action_sequence.length > 0 && (
                  <span className="muted"> · executed {c.action_sequence.join(' → ')}</span>
                )}
                {c.escalated_sequentially && (
                  <div className="muted" style={{ marginTop: 4 }}>
                    escalated to a contact after retries were exhausted
                  </div>
                )}
              </td>
            </tr>
            <tr>
              <td>counterfactual</td>
              <td className="mono">
                control arm: {c.control_confirmed ? 'recovered anyway' : 'did not recover'} ·
                {' '}naive arm: {c.naive_confirmed ? 'recovered' : 'did not recover'} using{' '}
                {c.naive_contacts} contact{c.naive_contacts === 1 ? '' : 's'}
              </td>
            </tr>
          </tbody>
        </table>
      </Section>

      {/* The most important component in the UI. Every action scored, the
          selection marked, and every rejection carrying its computed reason. */}
      <Section
        title="Alternatives considered"
        note="Every action was valued and policy-checked. Rejections carry the number or the rule that caused them, not a label."
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 180 }}>action</th>
                <th style={{ width: 90 }} className="right">uplift</th>
                <th style={{ width: 100 }} className="right">P(recover)</th>
                <th style={{ width: 90 }} className="right">cost</th>
                <th style={{ width: 110 }} className="right">net EV</th>
                <th style={{ width: 110 }}>outcome</th>
                <th>reason</th>
              </tr>
            </thead>
            <tbody>
              {[...alternatives]
                .sort((a, b) => b.incremental_ev - a.incremental_ev)
                .map((a) => (
                  <tr key={a.action} className={a.selected ? 'selected' : undefined}>
                    <td className="mono">
                      {a.selected && <span style={{ marginRight: 6 }}>●</span>}
                      {a.action}
                    </td>
                    <td className={`num${a.uplift < 0 ? ' neg' : ''}`}>{uplift(a.uplift)}</td>
                    <td className="num">{prob(a.p_treated)}</td>
                    <td className="num">{money(a.cost)}</td>
                    <td className={`num${a.incremental_ev < 0 ? ' neg' : ''}`}>
                      {money(a.incremental_ev)}
                    </td>
                    <td>
                      {a.selected
                        ? <Chip tone="recovered">selected</Chip>
                        : a.rejection_type === 'policy'
                          ? <Chip tone="blocked">{a.blocked_by}</Chip>
                          : <span className="muted" style={{ fontSize: 12 }}>
                              {REJECTION_LABEL[a.rejection_type] || '—'}
                            </span>}
                    </td>
                    <td className="muted mono" style={{ fontSize: 12, whiteSpace: 'normal' }}>
                      {a.selected ? '' : a.rejection_detail}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Policy">
        <PolicyBar audit={audit} state={c.state} stopReason={c.stop_reason} deferrals={c.deferrals} />
      </Section>

      <Section title="Execution">
        {/* One static row. It exists only to make the pipeline legible at a
            glance; the log below carries every detail. */}
        <div className="stages">
          {STAGES.map((s) => (
            <div key={s} className={`stage${reached[s] ? ' reached' : ''}`}>{s}</div>
          ))}
        </div>
        <div className="log">
          {audit.map((e, i) => (
            <div className="log-row" key={i}>
              <span className="muted">{clock(e.timestamp)}</span>
              <span>{e.event}</span>
              <span className="muted">{e.actor}</span>
              <span className="log-detail" title={e.detail}>
                {e.detail}
                {e.payload?.mode && <span className="muted"> · {e.payload.mode}</span>}
              </span>
            </div>
          ))}
        </div>
        {c.request_ids.length > 0 && (
          <div className="muted mono" style={{ fontSize: 12, marginTop: 8 }}>
            request ids: {c.request_ids.join(', ')}
          </div>
        )}
      </Section>

      <Section title="Outcome">
        <table className="kv">
          <tbody>
            <tr><td>attempted</td><td className="mono">{String(c.attempted)}</td></tr>
            <tr><td>payment succeeded</td><td className="mono">{String(c.payment_success)}</td></tr>
            <tr>
              <td>confirmed recovery</td>
              <td className="mono">
                {String(c.confirmed)}
                {c.confirmed && ` · ${moneyExact(c.amount_confirmed)}`}
              </td>
            </tr>
            <tr><td>intervention cost</td><td className="mono">{moneyExact(c.cost_spent)}</td></tr>
            <tr>
              <td>net value</td>
              <td className="mono">{moneyExact(c.amount_confirmed - c.cost_spent)}</td>
            </tr>
            {c.stop_reason && (
              <tr><td>stop reason</td><td className="mono">{c.stop_reason}</td></tr>
            )}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

function PolicyBar({ audit, state, stopReason, deferrals }) {
  const checks = audit.filter((e) => e.event === 'POLICY_CHECKED');
  const withRules = checks.find((e) => e.payload?.rules);
  const rules = withRules?.payload?.rules || [];
  const blocked = checks.find((e) => e.payload?.blocked_by)?.payload?.blocked_by;
  const applicable = rules.filter((r) => r.applies);
  const violations = applicable.filter((r) => !r.passed);

  const tone = blocked ? 'blocked' : state === 'ESCALATED' ? 'escalated' : '';

  if (!checks.length) {
    return (
      <div className="policy-bar">
        No policy evaluation — the case was never eligible.
        <div className="policy-line">{stopReason}</div>
      </div>
    );
  }

  return (
    <div className={`policy-bar ${tone}`}>
      {rules.length} rules evaluated, {applicable.length} applicable,{' '}
      {violations.length} violation{violations.length === 1 ? '' : 's'}
      {deferrals > 0 && `, ${deferrals} quiet-hour deferral${deferrals === 1 ? '' : 's'}`}
      {blocked && <> — blocked by <span className="mono">{blocked}</span></>}
      {/* Rules that PASSED are shown, not only those that failed. A product
          showing only its failures reads as a script. */}
      {rules.map((r) => (
        <div className="policy-line" key={r.rule_id}>
          <span style={{ color: !r.applies ? 'var(--border)' : r.passed ? 'var(--recovered)' : 'var(--blocked)' }}>
            {!r.applies ? '·' : r.passed ? '✓' : '✕'}
          </span>{' '}
          {r.rule_id} {r.name} — {r.detail}
        </div>
      ))}
    </div>
  );
}

function findBucket(reliability, confidence) {
  if (!reliability) return null;
  return reliability.find((b) => {
    const [lo, hi] = b.bucket.split('-').map(Number);
    return confidence >= lo && confidence < hi;
  });
}
