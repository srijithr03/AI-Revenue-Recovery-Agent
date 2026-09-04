// Thin fetch layer. The UI computes nothing; it renders what make eval wrote.

const BASE = '/api';

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      /* the API is down entirely; the status line is all we have */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const fetchSummary = () => get('/summary');
export const fetchCases = () => get('/cases');
export const fetchCase = (id) => get(`/case/${encodeURIComponent(id)}`);
