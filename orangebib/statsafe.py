# -*- coding: utf-8 -*-
"""
Statistical safeguards for Orange3-Biblium.
===========================================

Bibliometric contingency tables are often large and sparse, and the widgets
are used by researchers who may have limited statistical training. This module
provides the diagnostics that guard against technically valid but
substantively inappropriate interpretations:

- ``contingency_diagnostics``  Cochran-style checks on expected frequencies,
  plus Cramer's V as an effect size for the omnibus chi-square test.
- ``adjusted_residuals`` / ``residual_pvalues``  Haberman adjusted residuals,
  which are asymptotically standard normal under independence and therefore
  yield calibrated cell-level p-values (unlike the conservative Pearson
  standardized residuals used for visual encoding).
- ``adjust_pvalues``  Benjamini-Hochberg and Bonferroni corrections for the
  many simultaneous entity-group comparisons a single widget run produces.
- ``inertia_summary`` / ``inertia_warning``  eigenvalues, per-dimension and
  cumulative inertia for correspondence analysis, and a caution when a
  two-dimensional biplot captures only a small share of total inertia.

The module depends only on NumPy, holds no Orange or Qt state, and is covered
by unit tests in ``tests/test_statsafe.py``.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

__all__ = [
    "MIN_EXPECTED",
    "MAX_LOW_EXPECTED_SHARE",
    "MIN_CUMULATIVE_INERTIA",
    "contingency_diagnostics",
    "cramers_v",
    "adjusted_residuals",
    "residual_pvalues",
    "adjust_pvalues",
    "inertia_summary",
    "inertia_warning",
]

#: Cochran's rule of thumb: expected cell frequencies should reach 5.
MIN_EXPECTED = 5.0
#: Share of cells allowed below :data:`MIN_EXPECTED` before warning (Cochran).
MAX_LOW_EXPECTED_SHARE = 0.20
#: Cumulative inertia of the first two dimensions below which a biplot is
#: flagged as a partial representation of the table.
MIN_CUMULATIVE_INERTIA = 50.0


def _normal_sf(x: np.ndarray) -> np.ndarray:
    """Upper-tail probability of the standard normal distribution."""
    return 0.5 * np.vectorize(math.erfc)(np.asarray(x, dtype=float) / math.sqrt(2.0))


def cramers_v(chi2: float, n: float, shape: tuple[int, int]) -> float:
    """Cramer's V effect size for a contingency table.

    Returns 0.0 for degenerate tables (no observations or a single row or
    column), where the statistic is undefined.
    """
    rows, cols = shape
    k = min(rows, cols) - 1
    if n <= 0 or k < 1:
        return 0.0
    return float(np.sqrt(max(chi2, 0.0) / (n * k)))


def contingency_diagnostics(observed, expected, chi2: float | None = None) -> dict:
    """Assess whether a chi-square test on this table is trustworthy.

    Parameters
    ----------
    observed, expected:
        Contingency table and the expected frequencies under independence,
        as returned by ``scipy.stats.chi2_contingency``.
    chi2:
        Omnibus chi-square statistic; when given, Cramer's V is reported.

    Returns
    -------
    dict with ``n_cells``, ``n_low`` and ``share_low`` (cells with an expected
    frequency below :data:`MIN_EXPECTED`), ``min_expected``, ``n_total``,
    ``cramers_v``, ``sparse`` (Cochran's rule violated) and ``message``
    (human-readable caution, or an empty string when the table is adequate).
    """
    obs = np.asarray(observed, dtype=float)
    exp = np.asarray(expected, dtype=float)
    n_cells = int(exp.size)
    if n_cells == 0:
        return {"n_cells": 0, "n_low": 0, "share_low": 0.0, "min_expected": 0.0,
                "n_total": 0.0, "cramers_v": 0.0, "sparse": False, "message": ""}

    n_low = int(np.count_nonzero(exp < MIN_EXPECTED))
    share_low = n_low / n_cells
    min_expected = float(exp.min())
    n_total = float(obs.sum())
    v = cramers_v(chi2, n_total, obs.shape) if chi2 is not None else 0.0
    # Cochran: no expected frequency below 1, and at most 20 % below 5.
    sparse = share_low > MAX_LOW_EXPECTED_SHARE or min_expected < 1.0

    message = ""
    if sparse:
        message = (
            f"{n_low} of {n_cells} cells ({share_low:.0%}) have an expected "
            f"frequency below {MIN_EXPECTED:.0f} (minimum {min_expected:.2f}). "
            "The chi-square approximation is unreliable; rely on the "
            "permutation p-values, or raise the minimum frequency / lower "
            "the number of entities."
        )
    return {"n_cells": n_cells, "n_low": n_low, "share_low": share_low,
            "min_expected": min_expected, "n_total": n_total,
            "cramers_v": v, "sparse": sparse, "message": message}


def adjusted_residuals(observed, expected) -> np.ndarray:
    """Haberman adjusted residuals, asymptotically N(0, 1) under independence.

    The Pearson standardized residual ``(O - E) / sqrt(E)`` has a variance
    below 1, so thresholds such as |r| > 2 are conservative. Dividing by
    ``sqrt(E (1 - p_row) (1 - p_col))`` restores unit variance and makes
    cell-level p-values interpretable.
    """
    obs = np.asarray(observed, dtype=float)
    exp = np.asarray(expected, dtype=float)
    total = obs.sum()
    if total <= 0:
        return np.zeros_like(obs)
    p_row = obs.sum(axis=1, keepdims=True) / total
    p_col = obs.sum(axis=0, keepdims=True) / total
    var = exp * (1.0 - p_row) * (1.0 - p_col)
    var = np.where(var > 0, var, np.nan)
    with np.errstate(invalid="ignore"):
        res = (obs - exp) / np.sqrt(var)
    return np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)


def residual_pvalues(adj_res) -> np.ndarray:
    """Two-sided p-values for adjusted residuals under a normal reference."""
    return np.clip(2.0 * _normal_sf(np.abs(np.asarray(adj_res, dtype=float))), 0.0, 1.0)


def adjust_pvalues(pvalues: Iterable[float], method: str = "fdr_bh") -> np.ndarray:
    """Correct p-values for multiple comparisons.

    ``method`` is ``"fdr_bh"`` (Benjamini-Hochberg, the default: controls the
    false discovery rate and is the appropriate choice for the exploratory
    screening of many entities) or ``"bonferroni"`` (controls the family-wise
    error rate). NaNs are preserved. Implemented in NumPy so the package adds
    no statistics dependency beyond SciPy.
    """
    p = np.asarray(list(pvalues), dtype=float)
    out = np.full(p.shape, np.nan, dtype=float)
    finite = np.isfinite(p)
    n = int(finite.sum())
    if n == 0:
        return out
    vals = p[finite]

    if method == "bonferroni":
        out[finite] = np.clip(vals * n, 0.0, 1.0)
        return out
    if method != "fdr_bh":
        raise ValueError(f"unknown method: {method!r}")

    order = np.argsort(vals, kind="mergesort")
    ranked = vals[order]
    ranks = np.arange(1, n + 1, dtype=float)
    adjusted = ranked * n / ranks
    # Enforce monotonicity from the largest p-value downwards.
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    restored = np.empty(n, dtype=float)
    restored[order] = np.clip(adjusted, 0.0, 1.0)
    out[finite] = restored
    return out


def inertia_summary(singular_values, max_dims: int = 5) -> list[dict]:
    """Eigenvalues, per-dimension and cumulative inertia of a CA solution.

    ``singular_values`` are the singular values of the standardized residual
    matrix; eigenvalues (principal inertias) are their squares.
    """
    s = np.asarray(list(singular_values), dtype=float)
    if s.size == 0:
        return []
    eig = s ** 2
    total = float(eig.sum())
    if total <= 0:
        return []
    out = []
    cumulative = 0.0
    for d in range(min(len(eig), max_dims)):
        pct = float(eig[d] / total * 100.0)
        cumulative += pct
        out.append({"dim": d + 1,
                    "eigenvalue": float(eig[d]),
                    "inertia_pct": pct,
                    "cumulative_pct": cumulative})
    return out


def inertia_warning(summary: list[dict],
                    threshold: float = MIN_CUMULATIVE_INERTIA) -> str:
    """Caution when the plotted plane captures little of the total inertia."""
    if len(summary) < 2:
        return ""
    cumulative = summary[1]["cumulative_pct"]
    if cumulative >= threshold:
        return ""
    return (
        f"The first two dimensions account for {cumulative:.1f}% of total "
        "inertia, so the biplot is a partial picture of the table: distances "
        "off the plotted plane are not shown. Interpret positions as "
        "suggestive and confirm with the contingency and chi-square tables."
    )
