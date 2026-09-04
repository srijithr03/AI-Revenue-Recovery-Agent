"""Confidence intervals.

Two estimators, chosen for what they are actually being applied to:

  * Wilson score intervals for RECOVERY RATES. They are proportions, and Wilson
    behaves properly near 0 and 1 where the normal approximation does not.

  * Bootstrap percentile intervals for NET VALUE PER CASE. Net value is a
    heavily skewed quantity -- most cases contribute nothing and a few
    contribute thousands of rupees -- so a normal-approximation interval on its
    mean would understate the tail. Resampling makes no distributional
    assumption.

If an interval on a delta crosses zero, the harness says so in plain words
rather than reporting the point estimate as though it were a finding.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def wilson(successes: int, n: int, z: float = 1.959963985) -> tuple[float, float, float]:
    """Wilson score interval for a proportion. Returns (p, lo, hi)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(centre - half, 0.0), min(centre + half, 1.0)


def bootstrap_mean(values: Sequence[float], n_boot: int = 10000,
                   seed: int = 12345, alpha: float = 0.05
                   ) -> tuple[float, float, float]:
    """Percentile bootstrap CI for a mean. Returns (mean, lo, hi)."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(arr.mean()), float(lo), float(hi)


def bootstrap_diff(a: Sequence[float], b: Sequence[float], n_boot: int = 10000,
                   seed: int = 12345, alpha: float = 0.05
                   ) -> tuple[float, float, float]:
    """Percentile bootstrap CI for mean(a) - mean(b), resampling each arm
    independently -- the correct structure for a between-subjects comparison."""
    A = np.asarray(a, dtype=float)
    B = np.asarray(b, dtype=float)
    if A.size == 0 or B.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    ia = rng.integers(0, A.size, size=(n_boot, A.size))
    ib = rng.integers(0, B.size, size=(n_boot, B.size))
    diffs = A[ia].mean(axis=1) - B[ib].mean(axis=1)
    lo, hi = np.percentile(diffs, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(A.mean() - B.mean()), float(lo), float(hi)


def crosses_zero(lo: float, hi: float) -> bool:
    return lo <= 0.0 <= hi


def describe_delta(name: str, mean: float, lo: float, hi: float, unit: str = "Rs") -> str:
    verdict = ("NOT distinguishable from zero" if crosses_zero(lo, hi)
               else ("significantly positive" if lo > 0 else "significantly negative"))
    return (f"{name}: {unit} {mean:+,.2f}  95% CI [{unit} {lo:+,.2f}, "
            f"{unit} {hi:+,.2f}]  -- {verdict}")


def bootstrap_paired_diff(a: Sequence[float], b: Sequence[float],
                          n_boot: int = 10000, seed: int = 12345,
                          alpha: float = 0.05) -> tuple[float, float, float]:
    """Percentile bootstrap CI for the mean PAIRED difference a[i] - b[i].

    Only valid when both arms were run over the same cases with the same latent
    draws, which is possible here because the world is synthetic. Pairing
    removes between-case variance -- and between-case variance is enormous when
    amounts span Rs 99 to Rs 1,20,000 -- so the interval on the difference is
    far tighter than differencing two independent arm means.

    This is a simulation-only estimator. A merchant running a real holdout
    cannot pair, which is exactly why the randomised between-arms comparison is
    reported alongside it.
    """
    A = np.asarray(a, dtype=float)
    B = np.asarray(b, dtype=float)
    if A.size == 0 or A.size != B.size:
        return 0.0, 0.0, 0.0
    d = A - B
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, d.size, size=(n_boot, d.size))
    means = d[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(d.mean()), float(lo), float(hi)
