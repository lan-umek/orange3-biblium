"""Robustness tests: malformed, incomplete and degenerate bibliographic input.

Bibliographic exports are frequently incomplete — missing columns, empty
fields, stray separators, a single document, or a group that matches nothing.
The widget layer must degrade gracefully (empty or ``None`` results) rather
than raise, because an exception inside a worker thread surfaces to the user
only as a generic error message.
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("Orange")

from orangebib.widgets.owgroupassociations import OWGroupAssociations  # noqa: E402
from orangebib.widgets.owentityrelations import OWEntityRelations  # noqa: E402

def shim(cls, **attrs):
    """A plain object carrying the widget class's own methods.

    ``OWWidget.__new__`` builds the GUI and needs a running QApplication, so a
    real instance cannot be created headlessly; the computational methods are
    therefore copied onto an ordinary class. Defined locally rather than
    imported so this module stays independent of pytest's import mode.
    """
    # Dunder members are excluded: copying __init__ would run the widget
    # constructor, and its zero-argument super() is bound to the original
    # class, which this object is not an instance of.
    namespace = {k: v for k, v in vars(cls).items() if not k.startswith("__")}
    obj = type(cls.__name__ + "Shim", (), namespace)()
    obj.__dict__.update(attrs)
    return obj


@pytest.fixture
def widget():
    return shim(OWGroupAssociations, min_freq=1, top_n=100)


def _contingency(w, df, gm, column="Authors", label="Author"):
    return w._build_contingency(df, gm, list(gm.columns), column, label, "list", "; ")


# ------------------------------------------------------- missing / empty ----

def test_missing_entity_column_returns_empty(widget):
    df = pd.DataFrame({"Year": [2020, 2021]})
    gm = pd.DataFrame({"g": [1, 1]})
    assert _contingency(widget, df, gm).empty


def test_empty_dataframe_returns_empty(widget):
    df = pd.DataFrame({"Authors": []})
    gm = pd.DataFrame({"g": []})
    assert _contingency(widget, df, gm).empty


def test_all_missing_values_return_empty(widget):
    df = pd.DataFrame({"Authors": [None, np.nan, "", "  ", "nan", "NaN"]})
    gm = pd.DataFrame({"g": [1] * 6})
    assert _contingency(widget, df, gm).empty


def test_group_matching_no_documents_is_tolerated(widget):
    df = pd.DataFrame({"Authors": ["Smith, J.", "Doe, A."]})
    gm = pd.DataFrame({"present": [1, 1], "empty": [0, 0]})
    cont = _contingency(widget, df, gm)
    assert not cont.empty
    assert (cont["empty"] == 0).all()
    assert set(cont["Author"]) == {"Smith, J.", "Doe, A."}


# --------------------------------------------------- malformed separators ---

def test_stray_and_repeated_separators_are_cleaned(widget):
    df = pd.DataFrame({"Authors": ["; Smith, J.; ; Doe, A. ;", ";;", " Doe, A. "]})
    gm = pd.DataFrame({"g": [1, 1, 1]})
    cont = _contingency(widget, df, gm)
    names = set(cont["Author"])
    assert names == {"Smith, J.", "Doe, A."}
    assert "" not in names
    assert int(cont.set_index("Author").loc["Doe, A.", "g"]) == 2


def test_separator_cleaning_leaves_well_formed_values_untouched(widget):
    """Guard: cleaning must not alter results on correctly formatted exports.

    The published figures are computed from a well-formed sample, so entity
    extraction has to be bit-identical there; only malformed fragments may be
    affected.
    """
    df = pd.DataFrame({"Authors": [
        "Smith, J.; Doe, A.", "Waltman, L.; van Eck, N.J.",
        "Glanzel, W.", "Leydesdorff, L.; Bornmann, L.; Thelwall, M.",
        "Jones Jr.; O'Neill, M.",
    ]})
    gm = pd.DataFrame({"g": [1] * 5})
    names = set(_contingency(widget, df, gm)["Author"])
    assert names == {
        "Smith, J.", "Doe, A.", "Waltman, L.", "van Eck, N.J.", "Glanzel, W.",
        "Leydesdorff, L.", "Bornmann, L.", "Thelwall, M.", "Jones Jr.",
        "O'Neill, M.",
    }


def test_non_string_entity_values_do_not_crash(widget):
    df = pd.DataFrame({"Authors": [123, 45.6, True, "Smith, J."]})
    gm = pd.DataFrame({"g": [1, 1, 1, 1]})
    cont = _contingency(widget, df, gm)          # must not raise
    assert "Smith, J." in set(cont["Author"])


# ------------------------------------------------- degenerate statistics ----

def test_single_group_chi_square_returns_none_or_table(widget):
    mat = np.array([[3.0], [5.0], [2.0]])
    out = widget._calc_chi_square(mat, ["a", "b", "c"], ["only"], "Entity")
    assert out is None or isinstance(out, pd.DataFrame)


def test_zero_matrix_is_handled(widget):
    mat = np.zeros((3, 3))
    assert widget._calc_ca(mat, ["a", "b", "c"], ["x", "y", "z"], "Entity") is None
    div = widget._calc_diversity(mat, ["x", "y", "z"])
    assert (div["Shannon H"] == 0).all()
    assert (div["N entities"] == 0).all()


def test_single_entity_ca_returns_none(widget):
    mat = np.array([[4.0, 2.0, 1.0]])
    assert widget._calc_ca(mat, ["only"], ["x", "y", "z"], "Entity") is None


def test_perfectly_uniform_table_has_zero_residuals(widget):
    pytest.importorskip("scipy.stats")
    mat = np.full((4, 3), 6.0)
    out = widget._calc_chi_square(mat, list("abcd"), list("xyz"), "Entity")
    body = out[~out["Entity"].astype(str).str.startswith("[")]
    resid = body[[c for c in body.columns if c.endswith("Std. residual")]]
    assert np.allclose(resid.astype(float).values, 0.0, atol=1e-9)
    assert widget._chi_diagnostics["cramers_v"] == pytest.approx(0.0, abs=1e-9)


def test_diversity_of_single_entity_group():
    w = shim(OWGroupAssociations)
    div = w._calc_diversity(np.array([[10.0]]), ["g"])
    # One entity: no uncertainty, and evenness is undefined -> reported as 0.
    assert float(div.loc[0, "Shannon H"]) == pytest.approx(0.0)
    assert float(div.loc[0, "Shannon Evenness"]) == pytest.approx(0.0)
    assert float(div.loc[0, "Simpson D"]) == pytest.approx(1.0)


def test_entity_relations_empty_matrix_returns_none():
    w = shim(OWEntityRelations)
    assert w._calc_chi_square(np.empty((0, 0)), [], []) is None
    assert w._calc_ca(np.zeros((2, 2)), ["a", "b"], ["x", "y"]) is None


# ------------------------------------------------------ conversion layer ----

def test_conversion_handles_mixed_and_missing_types():
    from orangebib.base import df_to_table, table_to_df

    df = pd.DataFrame({
        "Title": ["a", None, "c"],
        "Cited by": [1, None, 3],
        "Mixed": ["x", 2, None],
    })
    table = df_to_table(df)
    assert table is not None
    back = table_to_df(table)
    assert len(back) == 3


def test_conversion_of_empty_frame_is_safe():
    from orangebib.base import df_to_table, table_to_df

    out = df_to_table(pd.DataFrame())
    assert out is None or len(out) == 0
    assert table_to_df(None).empty
