"""Cross-platform task runner.

Identical targets to the Makefile, for environments without `make` -- which
includes a stock Windows machine, where this project was built.

    python run.py data      regenerate the world and the historical log
    python run.py verify    check the generator property gates
    python run.py test      run the test suite
    python run.py eval      run the full three-arm evaluation
    python run.py serve     start the API on :8000
    python run.py ui        start the UI dev server on :5173
    python run.py all       data -> verify -> test -> eval
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def sh(cmd: list[str], cwd: str | None = None) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=cwd or ROOT)


def npm(args: list[str], cwd: str) -> int:
    exe = "npm.cmd" if os.name == "nt" else "npm"
    return sh([exe] + args, cwd=cwd)


TARGETS = {
    "data": lambda: sh([PY, "-m", "data.generator"]),
    "verify": lambda: sh([PY, "-m", "data.verify_world"]),
    "test": lambda: sh([PY, "-m", "pytest", "tests/", "-q"]),
    "eval": lambda: sh([PY, "-m", "eval.run_eval"]),
    "uplift-report": lambda: sh([PY, "-c",
                                 "from agent.uplift import fit_from_history;"
                                 "print(fit_from_history().report())"]),
    "serve": lambda: sh([PY, "-m", "uvicorn", "api.main:app", "--reload",
                         "--port", "8000"]),
    "ui": lambda: npm(["run", "dev"], os.path.join(ROOT, "ui")),
    "ui-install": lambda: npm(["install"], os.path.join(ROOT, "ui")),
}


def main() -> int:
    args = sys.argv[1:] or ["all"]
    if args == ["all"]:
        args = ["data", "verify", "test", "eval"]
    for t in args:
        if t not in TARGETS:
            print(f"unknown target {t!r}. available: {', '.join(sorted(TARGETS))}")
            return 2
        rc = TARGETS[t]()
        if rc != 0:
            print(f"\ntarget {t!r} failed with exit code {rc}")
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
