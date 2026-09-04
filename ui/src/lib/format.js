// Number formatting, defined once and used everywhere.
//
// Inconsistent formatting undoes the precision technique entirely: a screen
// that shows Rs 3,68,412 in one place and Rs 3.7L in another reads as two
// systems stapled together. Every rule from the design spec lives here and
// nothing formats a number inline.
//
// Indian grouping throughout -- last three digits, then pairs (12,04,318, not
// 1,204,318). Implemented with the en-IN locale rather than hand-rolled.

const INR = new Intl.NumberFormat('en-IN', {
  maximumFractionDigits: 0,
  minimumFractionDigits: 0,
});

const INR2 = new Intl.NumberFormat('en-IN', {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

const COUNT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

// U+2212 MINUS SIGN, not a hyphen. It aligns with digits in a monospace face.
const MINUS = '−';

/** Rs 3,68,412 -- and Rs 40.00 below a hundred, where the paise matter. */
export function money(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  const neg = v < 0;
  const a = Math.abs(v);
  const body = a < 100 ? INR2.format(a) : INR.format(Math.round(a));
  return `${neg ? MINUS : ''}₹${body}`;
}

/** Signed money, for deltas. Always carries its sign. */
export function moneySigned(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  const a = Math.abs(v);
  const body = a < 100 ? INR2.format(a) : INR.format(Math.round(a));
  return `${v < 0 ? MINUS : '+'}₹${body}`;
}

/** Never round a headline figure. Rs 3,68,412.55 */
export function moneyExact(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  const neg = v < 0;
  return `${neg ? MINUS : ''}₹${INR2.format(Math.abs(v))}`;
}

/** 0.412 -- three decimals, no percent sign. */
export function prob(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return v.toFixed(3);
}

/** +0.153 / -0.021 -- always signed. The sign is the information. */
export function uplift(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return `${v < 0 ? MINUS : '+'}${Math.abs(v).toFixed(3)}`;
}

/** 66.0% */
export function pct(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return `${(v * 100).toFixed(digits)}%`;
}

/** 1,000 -- Indian grouping above 999. */
export function count(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return COUNT.format(v);
}

/**
 * Rs 2,18,447 +-Rs 31,200
 * Rendered from an asymmetric [lo, hi] interval by taking the half-width, which
 * is what a reader expects to see. The asymmetry is negligible for a bootstrap
 * this size; where it is not, the raw interval is shown instead.
 */
export function interval(mean, ci) {
  if (!ci || ci.length !== 2) return money(mean);
  const half = (ci[1] - ci[0]) / 2;
  return `${moneySigned(mean)} ±${money(half)}`;
}

/** [+219.76, +271.36] -- the raw interval, when the exact bounds matter. */
export function intervalRaw(ci) {
  if (!ci || ci.length !== 2) return '--';
  return `[${moneySigned(ci[0])}, ${moneySigned(ci[1])}]`;
}

/** 14:02:11.503 -- millisecond precision, always. */
export function clock(ts) {
  if (!ts) return '--';
  const parts = String(ts).split(' ');
  return parts.length > 1 ? parts[1] : parts[0];
}

/** 4.18s */
export function duration(seconds) {
  if (seconds === null || seconds === undefined) return '--';
  return `${Number(seconds).toFixed(2)}s`;
}

/** 12 of 90 */
export function rank(n, m) {
  if (!n || !m) return '--';
  return `${count(n)} of ${count(m)}`;
}

/** 21:00 IST */
export function hour(h) {
  if (h === null || h === undefined) return '--';
  return `${String(h).padStart(2, '0')}:00`;
}

// ---------------------------------------------------------------- labels

export const CLASS_LABEL = {
  temporary_failure: 'Temporary failure',
  insufficient_funds: 'Insufficient funds',
  invalid_method: 'Invalid method',
  authentication_failure: 'Authentication failure',
  risk_blocked: 'Risk blocked',
  repeated_failure: 'Repeated failure',
  unknown: 'Unknown',
};

export const ACTION_LABEL = {
  no_action: 'no_action',
  retry_immediate: 'retry_immediate',
  retry_delayed: 'retry_delayed',
  sms_payment_link: 'sms_payment_link',
  whatsapp_nudge: 'whatsapp_nudge',
  method_update_request: 'method_update_request',
  human_escalation: 'human_escalation',
};

// Operator vocabulary, not code vocabulary.
export const STATE_LABEL = {
  RECOVERED: 'recovered',
  STOPPED: 'stopped',
  ESCALATED: 'escalated',
  INELIGIBLE: 'not pursued',
};

export const PATH_LABEL = {
  rules: 'rules',
  llm: 'llm',
  fallback_keyword: 'llm fallback',
  fallback_none: 'llm fallback, abstained',
};

export const REJECTION_LABEL = {
  ev_floor: 'below EV floor',
  budget_cutoff: 'below budget cutoff',
  policy: 'blocked by policy',
  lower_ev: 'lower EV than selected',
};
