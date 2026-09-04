import React from 'react';
import { count, interval, money, STATE_LABEL } from '../lib/format.js';

/* Loading, empty and error states.
 *
 * The UI reads static JSON, so loading is measured in milliseconds. A skeleton
 * screen for a 40ms load is theatre. One muted line is the honest treatment.
 */

export function Loading({ what = 'run' }) {
  return <div className="loading">Loading {what}…</div>;
}

export function Empty({ message }) {
  return <div className="empty">{message}</div>;
}

/* When an artifact is missing or malformed, say which file and what to run.
 * This is also the failure-recovery path for the UI itself: it degrades to a
 * clear instruction rather than a blank screen or a stack trace. */
export function ErrorState({ error }) {
  const msg = String(error?.message || error);
  return (
    <div className="error">
      {msg}
      {!msg.includes('make eval') && (
        <>
          {' '}Start the API with <code>python run.py serve</code>, and if the
          artifacts are missing run <code>python run.py eval</code> first.
        </>
      )}
    </div>
  );
}

export function Metric({ label, value, sub }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

export function MetricRow({ children }) {
  return <div className="metrics">{children}</div>;
}

export function Section({ title, note, children }) {
  return (
    <div className="section">
      {title && <h2 className="section-head">{title}</h2>}
      {note && <div className="section-note">{note}</div>}
      {children}
    </div>
  );
}

/* State chips carry a text label, never colour alone. */
export function StateChip({ state }) {
  const cls = {
    RECOVERED: 'chip-recovered',
    STOPPED: 'chip-stopped',
    ESCALATED: 'chip-escalated',
    INELIGIBLE: 'chip-ineligible',
  }[state] || 'chip-plain';
  return <span className={`chip ${cls}`}>{STATE_LABEL[state] || state}</span>;
}

export function Chip({ children, tone = 'plain' }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

export function StripItem({ label, value }) {
  return (
    <div className="strip-item">
      <div className="strip-label">{label}</div>
      <div className="strip-value">{value}</div>
    </div>
  );
}

/* Deltas carry their interval inline. Unusual in a dashboard, and it is what
 * marks the product as evidence-oriented rather than decorative. */
export function Delta({ mean, ci, significant }) {
  return (
    <span className="mono">
      {interval(mean, ci)}
      {significant === false && (
        <span className="muted"> · not distinguishable from zero</span>
      )}
    </span>
  );
}
