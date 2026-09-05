import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CLASS_LABEL, count, duration, interval, money, moneySigned, pct, prob, uplift,
} from '../lib/format.js';
import { Empty, Metric, MetricRow, Section, StateChip, StripItem } from '../components/common.jsx';

const COLUMNS = [
  { key: 'case_id', label: 'case', width: 100, mono: true },
  { key: 'amount', label: 'amount', width: 110, right: true },
  { key: 'failure_class', label: 'failure class', width: 170 },
  { key: 'uplift', label: 'uplift', width: 90, right: true },
  { key: 'incremental_ev', label: 'net EV', width: 110, right: true },
  { key: 'action', label: 'action', width: 180, mono: true },
  { key: 'state', label: 'state', width: 110 },
  { key: 'attempts', label: 'att', width: 80, right: true },
  { key: 'contacts', label: 'cont', width: 80, right: true },
];

export default function RunOverview({ summary, cases: casesOrNull, view, setView }) {
  const navigate = useNavigate();
  const cases = casesOrNull || [];
  const run = summary.run;
  const agent = summary.arms_paired.agent;
  const cmp = summary.comparison_paired;
  const f = summary.funnel;

  const filtered = useMemo(() => {
    let rows = cases;
    if (view.failureClass !== 'all') rows = rows.filter((c) => c.failure_class === view.failureClass);
    if (view.state !== 'all') rows = rows.filter((c) => c.state === view.state);
    if (view.only === 'skipped') rows = rows.filter((c) => c.action === 'no_action');
    if (view.only === 'contacted') rows = rows.filter((c) => c.contacts > 0);
    if (view.only === 'fallback') rows = rows.filter((c) => c.diag_path.startsWith('fallback'));
    if (view.only === 'wrong') rows = rows.filter((c) => !c.diagnosis_correct);

    const dir = view.sortDir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = a[view.sortKey];
      const y = b[view.sortKey];
      if (typeof x === 'string') return x.localeCompare(y) * dir;
      return ((x ?? 0) - (y ?? 0)) * dir;
    });
  }, [cases, view]);

  const sortBy = (key) =>
    setView((v) => ({
      ...v,
      sortKey: key,
      sortDir: v.sortKey === key && v.sortDir === 'desc' ? 'asc' : 'desc',
    }));

  const classes = useMemo(
    () => Array.from(new Set(cases.map((c) => c.failure_class))).sort(),
    [cases]
  );

  return (
    <div className="page">
      <h1 className="page-title">Run overview</h1>

      <div className="strip">
        <StripItem label="run" value={run.generated_at} />
        <StripItem label="seed" value={run.seed} />
        <StripItem label="holdout" value={`${count(run.n_holdout)} cases`} />
        <StripItem label="batch duration" value={duration(run.duration_seconds)} />
        <StripItem label="diagnosis rate" value={`${count(Math.round(run.throughput_cases_per_second))} cases/s`} />
        <StripItem
          label="execution"
          value={`${count(summary.execution.simulated_cases)} simulated · ${count(summary.execution.razorpay_test_cases)} razorpay test`}
        />
      </div>

      <Section>
        <MetricRow>
          <Metric
            label="revenue at risk"
            value={money(agent.at_risk)}
            sub={`${count(agent.n)} failed payments`}
          />
          <Metric
            label="net incremental recovered vs control"
            value={interval(cmp.agent_vs_control.net_per_case, cmp.agent_vs_control.ci)}
            sub="per case, 95% CI"
          />
          <Metric
            label="contacts used"
            value={`${count(agent.contacts)} / ${count(agent.budget)}`}
            sub={`naive arm used ${count(summary.arms_paired.naive.contacts)}`}
          />
          <Metric
            label="net incremental per contact"
            value={money(cmp.net_incremental_per_contact.agent)}
            sub={`naive ${money(cmp.net_incremental_per_contact.naive)}`}
          />
        </MetricRow>
      </Section>

      {/* Every tile is a PIPELINE count, on the same denominator, so the three
          terminal states add back to `eligible`:

              3,064 recovered + 5,274 stopped + 187 escalated = 8,525

          This used to show `recovered_confirmed` (3,575) here. That figure is
          correct but it is the agent ARM's confirmed recoveries across all
          12,000 cases -- it includes cases never actioned that came back on
          their own. Mixed into a funnel of pipeline counts it made the row fail
          to add up, and adding those three numbers is the first thing a reader
          does. It belongs in the arms table, where its denominator is stated,
          and it is still there. */}
      <Section
        title="Funnel"
        note="Pipeline counts on one denominator: recovered, stopped and escalated are the three terminal states and sum back to eligible."
      >
        <div className="funnel">
          <Stage label="failed" n={f.failed} />
          <Stage label="diagnosed" n={f.diagnosed} note={`${count(f.diagnosed_unknown)} unknown`} />
          <Stage label="eligible" n={f.eligible} note={`${count(f.ineligible)} not pursued`} />
          <Stage label="actioned" n={f.actioned} />
          <Stage label="recovered" n={f.recovered} note="terminal state" />
          <Stage label="stopped" n={f.stopped} />
          <Stage label="escalated" n={f.escalated} />
        </div>
      </Section>

      {/* The three-arm comparison sits on the landing screen, not buried on a
          later page. If the naive bot is winning, that fact appears here. */}
      <Section
        title="Three arms"
        note="Paired counterfactual over the full holdout: every case run through all three arms with the same latent draw. Net value is recovered revenue minus intervention cost."
      >
        <div style={{ border: '1px solid var(--border)', padding: '0 16px' }}>
          <ArmRow
            name="control"
            desc="no action at all — the counterfactual"
            arm={summary.arms_paired.control}
            delta={null}
          />
          <ArmRow
            name="naive"
            desc="retry 3×, then contact everyone not opted out"
            arm={summary.arms_paired.naive}
            delta={cmp.naive_vs_control}
          />
          <ArmRow
            name="agent"
            desc="uplift-ranked, budget-constrained, policy-gated"
            arm={summary.arms_paired.agent}
            delta={cmp.agent_vs_control}
          />
        </div>
        <div className="section-note" style={{ marginTop: 12 }}>
          Agent versus naive: <span className="mono">{interval(cmp.agent_vs_naive.net_per_case, cmp.agent_vs_naive.ci)}</span> per case
          {cmp.agent_vs_naive.significant
            ? cmp.agent_vs_naive.net_per_case > 0
              ? ' — the agent wins.'
              : ' — the agent loses.'
            : ' — statistically tied, on '
              + Math.round(summary.arms_paired.naive.contacts / summary.arms_paired.agent.contacts)
              + '× fewer contacts.'}
        </div>
      </Section>

      <Section title={`Cases`} note={`Showing ${count(cases.length)} of ${count(run.n_holdout)} holdout cases. Every metric above is computed over the full batch; this table is a slice weighted toward the cases that make the decision legible.`}>
        <div className="filters">
          <select
            value={view.failureClass}
            onChange={(e) => setView((v) => ({ ...v, failureClass: e.target.value }))}
          >
            <option value="all">all failure classes</option>
            {classes.map((c) => (
              <option key={c} value={c}>{CLASS_LABEL[c] || c}</option>
            ))}
          </select>
          <select value={view.state} onChange={(e) => setView((v) => ({ ...v, state: e.target.value }))}>
            <option value="all">all states</option>
            <option value="RECOVERED">recovered</option>
            <option value="STOPPED">stopped</option>
            <option value="ESCALATED">escalated</option>
            <option value="INELIGIBLE">not pursued</option>
          </select>
          {[
            ['skipped', 'deliberately skipped'],
            ['contacted', 'contacted'],
            ['fallback', 'llm fallback'],
            ['wrong', 'diagnosis wrong'],
          ].map(([k, label]) => (
            <button
              key={k}
              className={`chip-toggle${view.only === k ? ' active' : ''}`}
              onClick={() => setView((v) => ({ ...v, only: v.only === k ? null : k }))}
            >
              {label}
            </button>
          ))}
          <span className="muted mono" style={{ marginLeft: 'auto' }}>
            {count(filtered.length)} rows
          </span>
        </div>

        {!casesOrNull ? (
          <div className="loading">Loading cases…</div>
        ) : filtered.length === 0 ? (
          <Empty
            message={
              <>
                No cases match the current filters.{' '}
                <a href="#" onClick={(e) => { e.preventDefault(); setView({ ...view, failureClass: 'all', state: 'all', only: null }); }}>
                  Clear filters.
                </a>
              </>
            }
          />
        ) : (
          <div className="table-wrap table-scroll">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      style={{ width: c.width }}
                      className={`sortable${c.right ? ' right' : ''}${view.sortKey === c.key ? ' active' : ''}`}
                      onClick={() => sortBy(c.key)}
                      tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && sortBy(c.key)}
                    >
                      {c.label}
                      {view.sortKey === c.key && (
                        <span className="caret">{view.sortDir === 'desc' ? '▼' : '▲'}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr
                    key={c.case_id}
                    className="clickable"
                    tabIndex={0}
                    onClick={() => navigate(`/case/${c.case_id}`)}
                    onKeyDown={(e) => e.key === 'Enter' && navigate(`/case/${c.case_id}`)}
                  >
                    <td className="mono">{c.case_id}</td>
                    <td className="num">{money(c.amount)}</td>
                    <td>{CLASS_LABEL[c.failure_class] || c.failure_class}</td>
                    <td className={`num${c.uplift < 0 ? ' neg' : ''}`}>{uplift(c.uplift)}</td>
                    <td className={`num${c.incremental_ev < 0 ? ' neg' : ''}`}>{money(c.incremental_ev)}</td>
                    <td className="mono">{c.action}</td>
                    <td><StateChip state={c.state} /></td>
                    <td className="num">{c.attempts}</td>
                    <td className="num">{c.contacts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

function Stage({ label, n, note }) {
  return (
    <div className="funnel-stage">
      <div className="funnel-label">{label}</div>
      <div className="funnel-count">{count(n)}</div>
      {note && <div className="funnel-note">{note}</div>}
    </div>
  );
}

function ArmRow({ name, desc, arm, delta }) {
  return (
    <div className="arm-row">
      <div>
        <div className="arm-name">{name}</div>
      </div>
      <div className="arm-desc">{desc}</div>
      <div className="num mono" title="net value per case">
        {money(arm.net_per_case)}
        <div className="muted" style={{ fontSize: 12 }}>net / case</div>
      </div>
      <div className="num mono">
        {pct(arm.recovery_rate)}
        <div className="muted" style={{ fontSize: 12 }}>recovered</div>
      </div>
      <div className="num mono">
        {delta ? interval(delta.net_per_case, delta.ci) : '—'}
        <div className="muted" style={{ fontSize: 12 }}>
          {delta ? 'vs control' : 'baseline'}
        </div>
      </div>
    </div>
  );
}
