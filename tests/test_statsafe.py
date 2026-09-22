"""Unit tests for the statistical safeguards module.

These tests require only NumPy (SciPy and statsmodels are used for
cross-checking when available) and therefore run on every platform in CI
without Orange or Qt.
"""
import importlib.util
import os

import numpy as np
import pytest

# Loaded directly from its file so the test runs without Orange/Qt installed:
# importing the ``orangebib`` package would pull in the widget stack.
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "orangebib", "statsafe.py")
_spec = importlib.util.spec_from_file_location("orangebib_statsafe", _PATH)
statsafe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statsafe)


# ---------------------------------------------------------------- p-values --

def test_bonferroni():
    p = [0.01, 0.02, 0.5]
    out = statsafe.adjust_pvalues(p, method="bonferroni")
    assert np.allclose(out, [0.03, 0.06, 1.0])


def test_bh_known_values():
    # Benjamini-Hochberg on a textbook example.
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    out = statsafe.adjust_pvalues(p, method="fdr_bh")
    assert np.all(np.diff(out) >= -1e-12)          # monotone in sorted input
    assert out[0] == pytest.approx(0.008, rel=1e-9)
    assert np.all(out <= 1.0)
    assert np.all(out >= np.asarray(p) - 1e-12)    # never smaller than raw p


def test_bh_matches_statsmodels():
    sm = pytest.importorskip("statsmodels.stats.multitest")
    rng = np.random.default_rng(0)
    p = rng.uniform(size=200) ** 2
    mine = statsafe.adjust_pvalues(p, method="fdr_bh")
    theirs = sm.multipletests(p, method="fdr_bh")[1]
    assert np.allclose(mine, theirs)


def test_adjust_preserves_nan_and_rejects_unknown():
    out = statsafe.adjust_pvalues([0.01, np.nan, 0.02], method="fdr_bh")
    assert np.isnan(out[1]) and np.all(np.isfinite(out[[0, 2]]))
    assert np.all(np.isnan(statsafe.adjust_pvalues([np.nan])))
    with pytest.raises(ValueError):
        statsafe.adjust_pvalues([0.1], method="holm-bonferroni-typo")


# --------------------------------------------------------------- residuals --

def _independence(obs):
    """Expected frequencies and Pearson chi-square under independence."""
    obs = np.asarray(obs, dtype=float)
    exp = np.outer(obs.sum(1), obs.sum(0)) / obs.sum()
    return exp, float(((obs - exp) ** 2 / exp).sum())


def test_expected_frequencies_match_scipy():
    sp = pytest.importorskip("scipy.stats")
    obs = np.array([[30.0, 10.0], [12.0, 28.0]])
    _, _, _, exp_scipy = sp.chi2_contingency(obs, correction=False)
    exp_mine, _ = _independence(obs)
    assert np.allclose(exp_mine, exp_scipy)


def test_adjusted_residual_equals_sqrt_chi2_in_2x2():
    """For a 2x2 table every |adjusted residual| equals sqrt(chi-square)."""
    obs = np.array([[30.0, 10.0], [12.0, 28.0]])
    exp, chi2 = _independence(obs)
    res = statsafe.adjusted_residuals(obs, exp)
    assert np.allclose(np.abs(res), np.sqrt(chi2))


def test_adjusted_residuals_exceed_pearson():
    obs = np.array([[20.0, 8.0, 5.0], [7.0, 19.0, 6.0], [4.0, 5.0, 24.0]])
    exp, _ = _independence(obs)
    pearson = (obs - exp) / np.sqrt(exp)
    adj = statsafe.adjusted_residuals(obs, exp)
    nz = np.abs(pearson) > 1e-9
    assert np.all(np.abs(adj[nz]) >= np.abs(pearson[nz]) - 1e-12)


def test_residual_pvalues_are_calibrated():
    p = statsafe.residual_pvalues([0.0, 1.959963985, 2.575829304])
    assert np.allclose(p, [1.0, 0.05, 0.01], atol=1e-6)


def test_empty_table_is_handled():
    assert statsafe.adjusted_residuals([[0.0, 0.0]], [[0.0, 0.0]]).sum() == 0.0
    d = statsafe.contingency_diagnostics(np.empty((0, 0)), np.empty((0, 0)))
    assert d["n_cells"] == 0 and d["message"] == ""


# ------------------------------------------------------------- diagnostics --

def test_cramers_v_known_value():
    # Perfect association in a 2x2 table gives V = 1.
    obs = np.array([[25.0, 0.0], [0.0, 25.0]])
    assert statsafe.cramers_v(50.0, 50.0, obs.shape) == pytest.approx(1.0)
    assert statsafe.cramers_v(10.0, 0.0, (2, 2)) == 0.0     # degenerate
    assert statsafe.cramers_v(10.0, 50.0, (1, 4)) == 0.0    # single row


def test_sparse_table_is_flagged():
    obs = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    exp = np.full((3, 3), 1 / 3)
    d = statsafe.contingency_diagnostics(obs, exp, chi2=6.0)
    assert d["sparse"] and d["n_low"] == 9 and d["message"]


def test_adequate_table_is_not_flagged():
    obs = np.array([[40.0, 60.0], [55.0, 45.0]])
    exp = np.array([[47.5, 52.5], [47.5, 52.5]])
    d = statsafe.contingency_diagnostics(obs, exp, chi2=4.5)
    assert not d["sparse"] and d["message"] == ""
    assert d["min_expected"] == pytest.approx(47.5)


# ------------------------------------------------------------------- CA ----

def test_inertia_summary_cumulates_to_100():
    s = np.array([0.6, 0.4, 0.2])
    summary = statsafe.inertia_summary(s)
    assert [r["dim"] for r in summary] == [1, 2, 3]
    assert summary[-1]["cumulative_pct"] == pytest.approx(100.0)
    assert summary[0]["eigenvalue"] == pytest.approx(0.36)
    assert summary[0]["inertia_pct"] > summary[1]["inertia_pct"]


def test_inertia_warning_thresholds():
    weak = statsafe.inertia_summary([1.0, 0.9, 1.4])     # 2D plane is weak
    assert statsafe.inertia_warning(weak)
    strong = statsafe.inertia_summary([3.0, 2.0, 0.3])
    assert statsafe.inertia_warning(strong) == ""
    assert statsafe.inertia_warning([]) == ""
    assert statsafe.inertia_summary([]) == []
