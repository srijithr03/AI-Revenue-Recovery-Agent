// Thin fetch layer. The UI computes nothing; it renders what make eval wrote.
//
// Two pieces of hardening, both earned by watching the running app rather than
// reading the code:
//
// 1. IN-FLIGHT DEDUPING. React StrictMode invokes effects twice in development,
//    which fired two concurrent 1.7MB requests for the same artifact. Sharing
//    one promise per URL means the second caller waits on the first.
//
// 2. RETRY ON TRANSPORT FAILURE. Serving multi-megabyte JSON through the dev
//    proxy on this machine intermittently produced ERR_CONNECTION_RESET, which
//    left the app on a spinner forever. A network error is retried; an HTTP
//    error is not, because a 503 saying "run make eval" is a real answer and
//    retrying it just delays showing the user what to do.

const BASE = '/api';
const RETRIES = 2;
const RETRY_DELAY_MS = 400;

const inFlight = new Map();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchOnce(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      /* the API is down entirely; the status line is all we have */
    }
    const err = new Error(detail);
    err.http = true;
    throw err;
  }
  return res.json();
}

async function withRetry(url) {
  let last;
  for (let attempt = 0; attempt <= RETRIES; attempt += 1) {
    try {
      return await fetchOnce(url);
    } catch (err) {
      last = err;
      // An HTTP error is the server's considered answer. Only transport
      // failures are worth trying again.
      if (err.http) throw err;
      if (attempt < RETRIES) await sleep(RETRY_DELAY_MS * (attempt + 1));
    }
  }
  throw new Error(
    `${last?.message || 'network error'} — could not reach the API at ${BASE}. ` +
    'Start it with `python run.py serve`.'
  );
}

function get(path) {
  const url = BASE + path;
  if (inFlight.has(url)) return inFlight.get(url);
  const p = withRetry(url).finally(() => inFlight.delete(url));
  inFlight.set(url, p);
  return p;
}

export const fetchSummary = () => get('/summary');
export const fetchCases = () => get('/cases');
export const fetchCase = (id) => get(`/case/${encodeURIComponent(id)}`);
