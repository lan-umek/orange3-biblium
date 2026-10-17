#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reproduce the numerical results behind Figures 2-4 of the SoftwareX paper.

The script loads the OpenAlex sample dataset distributed with Biblium, applies
exactly the parameters used in the manuscript, and runs the same computational
methods that the widgets call. It therefore reproduces the published numbers
without a graphical session, and the resulting tables can be compared cell by
cell with what the widgets display.

Usage
-----
    python examples/reproduce_figures.py             # verify against expected/
    python examples/reproduce_figures.py --generate  # (re)write expected/

Exit status is 0 when every table matches the stored reference and 1
otherwise, so the script can be used as a reproducibility check in CI.

Parameters used in the manuscript
---------------------------------
Figure 2  Group Associations: entity = Sources (Journals), three publication
          period groups split at 2008/2014, top 10 entities, minimum
          frequency 5, balloon plot filtered to |standardized residual| >= 1.0.
Figure 3  Entity Relationships: Authors x Author Keywords, top 20 x top 20,
          minimum frequency 3.
Figure 4  Workflow illustration; its numerical branches are covered by the
          tables above.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXPECTED = os.path.join(HERE, "expected")
sys.path.insert(0, ROOT)

# Figure 2 parameters
PERIOD_CUTS = (2008, 2014)
FIG2_TOP_N, FIG2_MIN_FREQ = 10, 5
# Figure 3 parameters
FIG3_TOP_N, FIG3_MIN_FREQ = 20, 3

TOLERANCE = 1e-6

def _shim(cls, **attrs):
    """A plain object carrying the widget class's own methods.

    ``OWWidget.__new__`` builds the GUI and requires a running QApplication,
    so a real widget cannot be created headlessly. The computational methods
    depend only on a few settings, so they are copied onto an ordinary class:
    this runs exactly the code the widgets run, without any Qt object.
    """
    # Dunder members are excluded: copying __init__ would run the widget
    # constructor, and its zero-argument super() is bound to the original
    # class, which this object is not an instance of.
    namespace = {k: v for k, v in vars(cls).items() if not k.startswith("__")}
    obj = type(cls.__name__ + "Shim", (), namespace)()
    obj.__dict__.update(attrs)
    return obj


# --------------------------------------------------------------- data load --

def load_sample() -> pd.DataFrame:
    """Load the 613-record OpenAlex sample shipped with Biblium."""
    try:
        import biblium
        from biblium import BiblioAnalysis
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "biblium is required: pip install Orange3-Biblium") from exc

    data_dir = os.path.join(os.path.dirname(biblium.__file__), "data")
    path = os.path.join(data_dir, "open alex dataset.csv")
    if not os.path.exists(path):
        raise SystemExit(f"sample dataset not found: {path}")
    return BiblioAnalysis(path, db="oa").df


def resolve(df: pd.DataFrame, key: str) -> str:
    from orangebib.base import COLUMN_PATTERNS, find_column

    col = find_column(df, COLUMN_PATTERNS[key])
    if col is None:
        raise SystemExit(f"column for {key!r} not found; available: "
                         f"{list(df.columns)[:20]}")
    return col


def period_groups(df: pd.DataFrame) -> pd.DataFrame:
    """The three non-overlapping publication periods used in Figure 2."""
    year = pd.to_numeric(df[resolve(df, "year")], errors="coerce")
    lo, hi = PERIOD_CUTS
    return pd.DataFrame({
        f"-{lo}": (year <= lo).astype(int),
        f"{lo + 1}-{hi}": ((year > lo) & (year <= hi)).astype(int),
        f"{hi + 1}-": (year > hi).astype(int),
    }, index=df.index)


# ------------------------------------------------------------ computations --

def figure2_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    from orangebib.widgets.owgroupassociations import OWGroupAssociations

    w = _shim(OWGroupAssociations, min_freq=FIG2_MIN_FREQ, top_n=FIG2_TOP_N)

    gm = period_groups(df)
    groups = list(gm.columns)
    # "string" is the value type the Sources entity is configured with.
    label, col = "Source", resolve(df, "source")
    sep = w._detect_separator(df)
    cont = w._build_contingency(df, gm, groups, col, label, "string", sep)
    if cont.empty:
        raise SystemExit("Figure 2: empty contingency table")

    mat = cont[groups].values.astype(float)
    items = cont[label].tolist()
    return {
        "fig2_contingency": cont,
        "fig2_chi_square": w._calc_chi_square(mat, items, groups, label),
        "fig2_correspondence": w._calc_ca(mat, items, groups, label),
        "fig2_diversity": w._calc_diversity(mat, groups),
    }


def figure3_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    from orangebib.widgets.owentityrelations import OWEntityRelations

    # The widget's own entity selection and co-occurrence construction are
    # used, so this reproduces what the GUI computes rather than an
    # independent reimplementation of it.
    w = _shim(
        OWEntityRelations,
        row_min_freq=FIG3_MIN_FREQ, col_min_freq=FIG3_MIN_FREQ,
        row_top_n=FIG3_TOP_N, col_top_n=FIG3_TOP_N,
        row_max_items=0, col_max_items=0,
        row_include_text="", col_include_text="",
        row_exclude_text="", col_exclude_text="",
        row_regex_include="", col_regex_include="",
        row_regex_exclude="", col_regex_exclude="",
    )
    rows_col = resolve(df, "authors")
    cols_col = resolve(df, "keywords")
    sep = w._detect_separator(df)

    row_items = w._get_filtered_entities(df, rows_col, "list", sep, "row")
    col_items = w._get_filtered_entities(df, cols_col, "list", sep, "col")
    if not row_items or not col_items:
        raise SystemExit("Figure 3: no entities passed the filters")

    cooc = w._build_cooccurrence(df, rows_col, cols_col, "list", "list",
                                 row_items, col_items, sep)
    if cooc.empty:
        raise SystemExit("Figure 3: empty co-occurrence matrix")

    # _build_cooccurrence drops rows whose total is zero; keep the labels
    # aligned with the rows that survived.
    row_items = cooc["Row"].tolist()
    mat = cooc[col_items].values.astype(float)
    print(f"  Figure 3 matrix: {mat.shape[0]} x {mat.shape[1]}, "
          f"{int(mat.sum())} co-occurrences")
    return {
        "fig3_cooccurrence": cooc,
        "fig3_chi_square": w._calc_chi_square(mat, row_items, col_items),
        "fig3_correspondence": w._calc_ca(mat, row_items, col_items),
        "fig3_associations": w._calc_associations(mat, row_items, col_items),
    }


# ------------------------------------------------------- generate / verify --

def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Round floats so that platform-level noise does not cause mismatches."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(6)
    return out


def compare(name: str, got: pd.DataFrame, path: str) -> bool:
    if not os.path.exists(path):
        print(f"  MISSING reference for {name}: {path}")
        return False
    ref = pd.read_csv(path)
    got = _normalise(got.reset_index(drop=True))
    ref = _normalise(ref)
    if list(got.columns) != list(ref.columns):
        print(f"  FAIL {name}: columns differ\n"
              f"        expected {list(ref.columns)}\n"
              f"        got      {list(got.columns)}")
        return False
    if len(got) != len(ref):
        print(f"  FAIL {name}: {len(got)} rows, expected {len(ref)}")
        return False

    mismatches = []
    for col in ref.columns:
        a, b = got[col], ref[col]
        if pd.api.types.is_numeric_dtype(b) and pd.api.types.is_numeric_dtype(a):
            close = np.isclose(a.astype(float), b.astype(float),
                               rtol=0, atol=TOLERANCE, equal_nan=True)
        else:
            close = a.astype(str).values == b.astype(str).values
        if not np.all(close):
            bad = int((~np.asarray(close)).sum())
            mismatches.append(f"{col} ({bad} cells)")
    if mismatches:
        print(f"  FAIL {name}: {', '.join(mismatches)}")
        return False
    print(f"  OK   {name} ({len(got)} rows x {len(ref.columns)} columns)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true",
                        help="write the reference tables instead of checking them")
    args = parser.parse_args()

    os.makedirs(EXPECTED, exist_ok=True)
    df = load_sample()
    print(f"Sample dataset: {len(df)} records, {len(df.columns)} columns")

    tables: dict[str, pd.DataFrame] = {}
    tables.update(figure2_tables(df))
    tables.update(figure3_tables(df))

    ok = True
    for name, table in tables.items():
        if table is None:
            print(f"  SKIP {name}: not computed (optional dependency missing)")
            continue
        path = os.path.join(EXPECTED, f"{name}.csv")
        if args.generate:
            table.to_csv(path, index=False)
            print(f"  wrote {os.path.relpath(path, ROOT)} ({len(table)} rows)")
        else:
            ok &= compare(name, table, path)

    if args.generate:
        print("\nReference tables written. Commit them together with the "
              "workflow files so the figures remain reproducible.")
        return 0
    print("\nAll tables reproduced." if ok else "\nReproduction FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
