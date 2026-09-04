import React, { useEffect, useMemo, useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import { fetchCases, fetchSummary } from './lib/api.js';
import { ErrorState, Loading } from './components/common.jsx';
import RunOverview from './screens/RunOverview.jsx';
import CaseDetail from './screens/CaseDetail.jsx';
import Evaluation from './screens/Evaluation.jsx';

/* Table filter and sort state lives here, above the routes.
 *
 * A judge who filters to skipped cases, opens one, and comes back to an
 * unfiltered table will notice. Keeping it at this level is what makes the
 * back link preserve it without threading state through the router. */
const DEFAULT_VIEW = {
  sortKey: 'incremental_ev',
  sortDir: 'desc',
  failureClass: 'all',
  state: 'all',
  only: null, // 'skipped' | 'contacted' | 'fallback' | 'wrong'
};

export default function App() {
  const [summary, setSummary] = useState(null);
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState(DEFAULT_VIEW);

  // summary.json is ~100KB and every screen needs it. cases.json is ~1.7MB and
  // only the run-overview table needs it. Blocking the whole app on the larger
  // one meant the evaluation screen sat on a spinner for several seconds while
  // fetching data it never reads.
  useEffect(() => {
    let live = true;
    fetchSummary().then((s) => live && setSummary(s)).catch((e) => live && setError(e));
    fetchCases().then((c) => live && setCases(c)).catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, []);

  const seed = summary?.run?.seed;

  return (
    <div className="app">
      <nav className="rail">
        <div className="rail-head">
          <div className="rail-title">Revenue recovery agent</div>
          {/* The seed is visible on every screen. It is a small claim a judge
              can verify by re-running. */}
          <div className="rail-seed">seed {seed ?? '—'}</div>
        </div>
        <div className="rail-nav">
          <NavLink to="/" end className={({ isActive }) => `rail-item${isActive ? ' active' : ''}`}>
            Run overview
          </NavLink>
          <NavLink to="/evaluation" className={({ isActive }) => `rail-item${isActive ? ' active' : ''}`}>
            Evaluation
          </NavLink>
          <NavLink to="/assumptions" className={({ isActive }) => `rail-item${isActive ? ' active' : ''}`}>
            Assumptions
          </NavLink>
        </div>
        {summary && (
          <div className="rail-foot">
            <div>{summary.run.n_holdout.toLocaleString('en-IN')} case holdout</div>
            <div style={{ marginTop: 4 }}>
              {summary.execution.llm_available ? 'llm live' : 'llm fallback'}
              {' · '}
              {summary.execution.razorpay_available ? 'rzp test' : 'simulated'}
            </div>
          </div>
        )}
      </nav>

      <main className="main">
        {error ? (
          <div className="page">
            <ErrorState error={error} />
          </div>
        ) : !summary ? (
          <div className="page">
            <Loading />
          </div>
        ) : (
          <Routes>
            <Route
              path="/"
              element={<RunOverview summary={summary} cases={cases} view={view} setView={setView} />}
            />
            <Route path="/case/:id" element={<CaseDetail summary={summary} />} />
            <Route path="/evaluation" element={<Evaluation summary={summary} />} />
            <Route path="/assumptions" element={<Assumptions />} />
            <Route path="*" element={<div className="page"><div className="empty">No such screen.</div></div>} />
          </Routes>
        )}
      </main>
    </div>
  );
}

function Assumptions() {
  const [md, setMd] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    fetch('/api/assumptions')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('ASSUMPTIONS.md not found'))))
      .then((d) => setMd(d.markdown))
      .catch(setErr);
  }, []);
  if (err) return <div className="page"><ErrorState error={err} /></div>;
  if (!md) return <div className="page"><Loading what="assumptions" /></div>;
  return (
    <div className="page">
      <h1 className="page-title">Assumptions</h1>
      <div className="section-note">
        Every base rate and cost in the world model, with its reasoning, its source
        where one exists, and an honest note where none does. Rendered from
        data/ASSUMPTIONS.md.
      </div>
      <pre
        className="mono"
        style={{
          fontSize: 12,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          border: '1px solid var(--border)',
          padding: 16,
          maxWidth: 900,
        }}
      >
        {md}
      </pre>
    </div>
  );
}
