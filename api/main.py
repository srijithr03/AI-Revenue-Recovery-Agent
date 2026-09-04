"""Read-only API over the evaluation artifacts.

It exists for one reason: `audits.json` is ~11 MB, and shipping that to a
browser so a judge can open one case would be silly. The API loads the
artifacts once, serves the case list in bulk, and serves the heavy per-case
detail on demand.

It computes NOTHING. Every number it returns was written by `make eval`. If a
screen needs a value that is not here, the fix belongs in eval/run_eval.py --
the moment this layer calculates something, that number stops being
reproducible from the seed.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "eval", "results")

app = FastAPI(title="Revenue Recovery Agent", version="1.0",
              description="Read-only view over eval/results/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_cache: dict[str, Any] = {}


def artifact(name: str) -> Any:
    """Load an artifact, with a clear error rather than a stack trace."""
    if name in _cache:
        return _cache[name]
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=503,
            detail=f"eval/results/{name} not found. Run `make eval` "
                   f"(or `python run.py eval`).")
    try:
        with open(path, encoding="utf-8") as fh:
            _cache[name] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"eval/results/{name} is malformed ({exc}). "
                   f"Re-run `make eval`.")
    return _cache[name]


@app.get("/api/health")
def health() -> dict[str, Any]:
    present = {n: os.path.exists(os.path.join(RESULTS, n))
               for n in ("summary.json", "cases.json", "alternatives.json",
                         "audits.json")}
    return {"ok": all(present.values()), "artifacts": present,
            "results_dir": RESULTS}


@app.get("/api/summary")
def summary() -> Any:
    return artifact("summary.json")


@app.get("/api/cases")
def cases() -> Any:
    """Every case row the UI shows. Small enough to send in one go."""
    return artifact("cases.json")


@app.get("/api/case/{case_id}")
def case_detail(case_id: str) -> Any:
    rows = artifact("cases.json")
    row = next((c for c in rows if c["case_id"] == case_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found")
    return {
        "case": row,
        "alternatives": artifact("alternatives.json").get(case_id, []),
        "audit": artifact("audits.json").get(case_id, []),
    }


@app.get("/api/assumptions")
def assumptions() -> JSONResponse:
    """Served so the evaluation screen can link straight to it."""
    path = os.path.join(ROOT, "data", "ASSUMPTIONS.md")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="ASSUMPTIONS.md not found")
    with open(path, encoding="utf-8") as fh:
        return JSONResponse({"markdown": fh.read()})
