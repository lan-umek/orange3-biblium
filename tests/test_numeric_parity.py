"""Numerical parity tests for the Orange3-Biblium widget layer.

The analytical methods themselves live in the Biblium library and have been
validated against five established Python bibliometric libraries. This module
tests the *additional* layer that the add-on introduces: entity extraction and
contingency construction, the statistics computed inside the widgets, and the
Orange Table <-> pandas conversion through which every widget communicates.

Each widget result is compared against an independent reference computed in
the test itself (SciPy, NumPy or a closed-form expression) and, where the
operation has a direct Biblium counterpart, against the Biblium API on the
same input with the same parameters.

The numerical methods are exercised on a lightweight stand-in object (see
``shim``) so that no Qt object is constructed; this keeps the tests fast and
headless-safe on all three supported platforms.
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("Orange")

from orangebib.widgets.owgroupassociations import OWGroupAssociations  # noqa: E402
from orangebib.widgets.owentityrelations import OWEntityRelations  # noqa: E402

TOL = 1e-9

_SKIP_ATTRS = {"__dict__", "__weakref__"}


def shim(cls, **attrs):
    """A plain object carrying the widget class's own methods.

    ``OWWidget.__new__`` builds the GUI and needs a running QApplication, so a
    real instance cannot be created headlessly. The computational methods,
    however, depend only on a few settings, so they are copied onto an
    ordinary class: this exercises exactly the code the widgets run, without
    constructing any Qt object.
    """
    namespace = {k: v for k, v in vars(cls).items() if k not in _SKIP_ATTRS}
    obj = type(cls.__name__ + "Shim", (), namespace)()
    obj.__dict__.update(attrs)
    return obj


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def docs():
    """Small deterministic bibliographic table with overlapping entities."""
    return pd.DataFrame({
        "Authors": [
            "Smith, J.; Doe, A.", "Doe, A.", "Smith, J.; Roe, R.",
            "Roe, R.; Doe, A.", "Smith, J.", "Roe, R.",
            "Doe, A.; Smith, J.", "Roe, R.; Smith, J.", "Doe, A.", "Smith, J.",
        ],
        "Author Keywords": [
            "bibliometrics; citation analysis", "citation analysis",
            "bibliometrics", "science mapping; bibliometrics",
            "citation analysis", "science mapping",
            "bibliometrics; science mapping", "citation analysis",
            "bibliometrics", "science mapping; citation analysis",
        ],
        "Year": [2005, 2007, 2009, 2011, 2012, 2013, 2016, 2017, 2018, 2020],
    })


@pytest.fixture
def groups_matrix(docs):
    """Three non-overlapping period groups, as Setup Groups would produce."""
    year = docs["Year"]
    return pd.DataFrame({
        "-2009": (year <= 2009).astype(int),
        "2010-2014": ((year > 2009) & (year <= 2014)).astype(int),
        "2015-": (year > 2014).astype(int),
    })


@pytest.fixture
def assoc_widget():
    return shim(OWGroupAssociations, min_freq=1, top_n=100)


def _contingency(widget, docs, gm, column, label):
    groups = list(gm.columns)
    return widget._build_contingency(docs, gm, groups, column, label, "list", "; ")


def _independence(mat):
    exp = np.outer(mat.sum(1), mat.sum(0)) / mat.sum()
    return exp, float(((mat - exp) ** 2 / exp).sum())


def _overall_row(df, label):
    """The '[Overall: ...]' summary row appended to a chi-square table."""
    mask = df[label].astype(str).str.startswith("[Overall")
    assert mask.any(), "chi-square table is missing its summary row"
    return df.loc[mask].iloc[0]


# ------------------------------------------------- entity extraction/counting

def test_contingency_matches_manual_counts(assoc_widget, docs, groups_matrix):
    """Semicolon-separated entities are split and cross-tabulated correctly."""
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", "Author")
    got = cont.set_index("Author")[list(groups_matrix.columns)]

    expected = {}
    for g in groups_matrix.columns:
        sub = docs.loc[groups_matrix[g].astype(bool), "Authors"]
        for cell in sub:
            for name in (p.strip() for p in cell.split(";")):
                expected.setdefault(name, dict.fromkeys(groups_matrix.columns, 0))
                expected[name][g] += 1

    assert set(got.index) == set(expected)
    for name, per_group in expected.items():
        for g, n in per_group.items():
            assert int(got.loc[name, g]) == n, f"{name} / {g}"
    # Totals are internally consistent with the per-group columns.
    assert (cont["Total"].values
            == cont[list(groups_matrix.columns)].sum(axis=1).values).all()


def test_contingency_matches_biblium_counts(assoc_widget, docs, groups_matrix):
    """Per-group entity counts agree with Biblium's own count_occurrences."""
    utilsbib = pytest.importorskip("biblium.utilsbib")
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", "Author")
    got = cont.set_index("Author")

    for g in groups_matrix.columns:
        sub = docs.loc[groups_matrix[g].astype(bool)].copy()
        ref = utilsbib.count_occurrences(
            sub, "Authors", count_type="list", item_column_name="Author", sep="; ")
        ref_counts = dict(zip(ref["Author"], ref.iloc[:, 1]))
        for name, n in ref_counts.items():
            assert int(got.loc[name, g]) == int(n), f"{name} / {g}"


def test_min_frequency_and_top_n_filters(assoc_widget, docs, groups_matrix):
    assoc_widget.min_freq = 4
    high = _contingency(assoc_widget, docs, groups_matrix, "Author Keywords",
                        "Author Keyword")
    assert (high["Total"] >= 4).all()

    assoc_widget.min_freq, assoc_widget.top_n = 1, 2
    topn = _contingency(assoc_widget, docs, groups_matrix, "Author Keywords",
                        "Author Keyword")
    assert len(topn) == 2
    assert topn["Total"].is_monotonic_decreasing


# ------------------------------------------------------------- chi-square ---

def test_chi_square_matches_scipy(assoc_widget, docs, groups_matrix):
    sp = pytest.importorskip("scipy.stats")
    label, groups = "Author", list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", label)
    mat = cont[groups].values.astype(float)
    items = cont[label].tolist()

    chi2_ref, _, dof_ref, exp_ref = sp.chi2_contingency(mat)
    out = assoc_widget._calc_chi_square(mat, items, groups, label)
    assert out is not None

    overall = _overall_row(out, label)
    assert float(overall["Chi-square contribution"]) == pytest.approx(chi2_ref, rel=1e-4)
    assert f"df={dof_ref}" in str(overall[label])

    body = out[~out[label].astype(str).str.startswith("[")].set_index(label)
    for i, item in enumerate(items):
        for j, g in enumerate(groups):
            assert float(body.loc[item, f"{g} Observed"]) == mat[i, j]
            assert float(body.loc[item, f"{g} Expected"]) == pytest.approx(
                exp_ref[i, j], abs=5e-3)
            assert float(body.loc[item, f"{g} Std. residual"]) == pytest.approx(
                (mat[i, j] - exp_ref[i, j]) / np.sqrt(exp_ref[i, j]), abs=5e-3)


def test_corrected_pvalues_are_conservative(assoc_widget, docs, groups_matrix):
    pytest.importorskip("scipy.stats")
    label, groups = "Author", list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", label)
    mat = cont[groups].values.astype(float)
    out = assoc_widget._calc_chi_square(mat, cont[label].tolist(), groups, label)
    body = out[~out[label].astype(str).str.startswith("[")]

    raw = body["Perm. p-value"].astype(float).values
    bh = body["Perm. p (BH)"].astype(float).values
    bonf = body["Perm. p (Bonferroni)"].astype(float).values
    assert np.all(bh >= raw - 1e-9)
    assert np.all(bonf >= bh - 1e-9)
    assert np.all(bonf <= 1.0)


def test_adjusted_residuals_reported(assoc_widget, docs, groups_matrix):
    pytest.importorskip("scipy.stats")
    label, groups = "Author", list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", label)
    mat = cont[groups].values.astype(float)
    exp, _ = _independence(mat)
    out = assoc_widget._calc_chi_square(mat, cont[label].tolist(), groups, label)
    body = out[~out[label].astype(str).str.startswith("[")].set_index(label)

    total = mat.sum()
    p_row = mat.sum(1, keepdims=True) / total
    p_col = mat.sum(0, keepdims=True) / total
    ref = (mat - exp) / np.sqrt(exp * (1 - p_row) * (1 - p_col))
    for i, item in enumerate(cont[label]):
        for j, g in enumerate(groups):
            assert float(body.loc[item, f"{g} Adj. residual"]) == pytest.approx(
                ref[i, j], abs=5e-3)


def test_diagnostics_reported_for_sparse_table(assoc_widget, docs, groups_matrix):
    pytest.importorskip("scipy.stats")
    label, groups = "Author Keyword", list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Author Keywords", label)
    mat = cont[groups].values.astype(float)
    assoc_widget._calc_chi_square(mat, cont[label].tolist(), groups, label)
    diag = assoc_widget._chi_diagnostics
    assert diag["n_cells"] == mat.size
    assert diag["n_total"] == pytest.approx(mat.sum())
    assert 0.0 <= diag["cramers_v"] <= 1.0


# ------------------------------------------------- correspondence analysis ---

def test_correspondence_analysis_matches_reference(assoc_widget, docs, groups_matrix):
    """Widget CA reproduces the standard SVD-of-standardized-residuals solution."""
    label, groups = "Author", list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", label)
    mat = cont[groups].values.astype(float)
    items = cont[label].tolist()

    # Independent reference implementation.
    P = mat / mat.sum()
    r = P.sum(1, keepdims=True)
    c = P.sum(0, keepdims=True)
    S = (P - r @ c) / np.sqrt(r @ c)
    U, s, Vt = np.linalg.svd(S, full_matrices=False)
    row_coords = (U * s) / np.sqrt(r)
    total_inertia = float((s ** 2).sum())

    out = assoc_widget._calc_ca(mat, items, groups, label)
    assert out is not None
    ent = out[out["Type"] == "Entity"].set_index(label)
    for i, item in enumerate(items):
        # Singular vectors are sign-indeterminate; compare magnitudes.
        assert abs(float(ent.loc[item, "Dim 1"])) == pytest.approx(
            abs(row_coords[i, 0]), abs=1e-5)

    info = out[out["Type"] == "Info"]
    assert float(info.iloc[0]["Dim 1"]) == pytest.approx(
        s[0] ** 2 / total_inertia * 100, abs=1e-2)


def test_inertia_is_normalised_over_all_dimensions(assoc_widget):
    """Percentages must sum to 100 across the full solution, not the top k."""
    rng = np.random.default_rng(3)
    mat = rng.integers(1, 40, size=(20, 20)).astype(float)
    items = [f"e{i}" for i in range(20)]
    groups = [f"g{j}" for j in range(20)]
    assoc_widget._calc_ca(mat, items, groups, "Entity")
    summary = assoc_widget._ca_inertia
    assert sum(r["inertia_pct"] for r in summary) == pytest.approx(100.0, abs=1e-6)
    assert summary[-1]["cumulative_pct"] == pytest.approx(100.0, abs=1e-6)
    assert summary[0]["inertia_pct"] < 100.0


# ------------------------------------------------------------- diversity ----

def test_diversity_matches_closed_form(assoc_widget, docs, groups_matrix):
    groups = list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", "Author")
    mat = cont[groups].values.astype(float)
    out = assoc_widget._calc_diversity(mat, groups).set_index("Group")

    for j, g in enumerate(groups):
        col = mat[:, j]
        p = col[col > 0] / col.sum()
        shannon = -np.sum(p * np.log(p))
        simpson = np.sum(p ** 2)
        assert float(out.loc[g, "Shannon H"]) == pytest.approx(shannon, abs=1e-4)
        assert float(out.loc[g, "Simpson D"]) == pytest.approx(simpson, abs=1e-6)
        assert float(out.loc[g, "Simpson 1-D"]) == pytest.approx(1 - simpson, abs=1e-6)
        assert int(out.loc[g, "N entities"]) == len(p)
        assert int(out.loc[g, "N documents"]) == int(col.sum())


def test_svd_matches_numpy(assoc_widget, docs, groups_matrix):
    groups = list(groups_matrix.columns)
    cont = _contingency(assoc_widget, docs, groups_matrix, "Authors", "Author")
    mat = cont[groups].values.astype(float)
    out = assoc_widget._calc_svd(mat, cont["Author"].tolist(), groups, "Author")

    normalised = mat / mat.sum(0, keepdims=True)
    _, s_ref, _ = np.linalg.svd(normalised, full_matrices=False)
    sing = out[out["Type"] == "Singular value"]["Value"].astype(float).values
    assert np.allclose(sing, s_ref[:len(sing)], atol=1e-5)


# ----------------------------------------------- entity relationships layer --

def test_entity_relationships_chi_square_matches_scipy():
    sp = pytest.importorskip("scipy.stats")
    w = shim(OWEntityRelations)
    mat = np.array([[12.0, 3.0, 5.0], [4.0, 15.0, 6.0], [7.0, 5.0, 18.0]])
    rows, cols = ["a1", "a2", "a3"], ["k1", "k2", "k3"]
    chi2_ref, _, _, exp_ref = sp.chi2_contingency(mat)

    out = w._calc_chi_square(mat, rows, cols)
    body = out[~out["Row"].astype(str).str.startswith("[")]
    cell = body.set_index(["Row", "Column"])
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            assert float(cell.loc[(r, c), "Expected"]) == pytest.approx(
                exp_ref[i, j], abs=5e-3)
    assert float(body["Contribution"].astype(float).sum()) == pytest.approx(
        chi2_ref, rel=1e-3)
    # Cell-level p-values are corrected across all row x column comparisons.
    assert (body["p (BH)"].astype(float).values
            >= body["p-value"].astype(float).values - 1e-9).all()


# ------------------------------------------------------- conversion layer ----

def test_table_roundtrip_preserves_values(docs):
    """Orange Table <-> pandas conversion is the interface every widget uses."""
    from orangebib.base import df_to_table, table_to_df

    table = df_to_table(docs)
    assert table is not None
    back = table_to_df(table)
    assert len(back) == len(docs)
    for col in ("Authors", "Author Keywords"):
        assert [str(v) for v in back[col]] == list(docs[col])
    assert np.allclose(back["Year"].astype(float).values,
                       docs["Year"].astype(float).values)


def test_roundtrip_preserves_missing_values():
    from orangebib.base import df_to_table, table_to_df

    df = pd.DataFrame({"Title": ["a", None, "c"], "Cited by": [3.0, np.nan, 7.0]})
    back = table_to_df(df_to_table(df))
    assert len(back) == 3
    assert float(back["Cited by"].iloc[0]) == 3.0
    assert float(back["Cited by"].iloc[2]) == 7.0
    assert pd.isna(pd.to_numeric(back["Cited by"], errors="coerce").iloc[1])
