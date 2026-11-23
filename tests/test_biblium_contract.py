"""Contract test: every Biblium name the widgets import must exist.

Most widgets import Biblium inside ``try/except`` so that Orange still starts
when an optional part is missing. The price is that an upstream rename does
not raise: the widget quietly switches a feature off. That happened when
Biblium moved its permutation and Firth modules into ``biblium.utilsbib``;
the import smoke tests kept passing while Permutation Test stopped working.

This test closes the gap. It reads the widget sources, collects every
``from biblium... import name`` statement wherever it is written, and checks
each one against the installed Biblium. A failure means Biblium changed its
interface and the add-on must follow before the next release.

Imports that fail only because an optional third-party package (for example
gensim) is not installed are skipped, not failed.
"""
import ast
import glob
import importlib
import os

import pytest

biblium = pytest.importorskip("biblium")

PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "orangebib")

# Locations kept only as a fallback for older Biblium releases; the widgets
# try the current location first.
LEGACY = {
    ("biblium.utilsbib_modules.firth", "firth_logit"),
    ("biblium.utilsbib_modules", "permutation"),
}

# Names the widgets reach as attributes rather than through an import.
ATTRIBUTES = [
    ("biblium.utilsbib", "assoc_permutation_test"),
    ("biblium.utilsbib", "firth_logit"),
    ("biblium.utilsbib", "count_occurrences"),
    ("biblium.merge", "combine_databases"),
    ("biblium.openalex_api", "SORT_OPTIONS"),
    ("biblium.openalex_api", "SORT_LABELS"),
    ("biblium.openalex_api", "resolve_sort"),
]


def _collect():
    found = set()
    files = glob.glob(os.path.join(PACKAGE, "*.py")) \
        + glob.glob(os.path.join(PACKAGE, "widgets", "ow*.py"))
    for path in files:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.level == 0
                    and node.module and node.module.split(".")[0] == "biblium"):
                for alias in node.names:
                    found.add((node.module, alias.name, os.path.basename(path)))
    return sorted(found)


IMPORTS = _collect()


def _resolve(module, name):
    """Import ``name`` from ``module``; skip when a third-party package is missing."""
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] != "biblium":
            pytest.skip(f"optional dependency not installed: {exc.name}")
        raise
    if hasattr(mod, name):
        return
    try:                                   # ``from package import submodule``
        importlib.import_module(f"{module}.{name}")
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] != "biblium":
            pytest.skip(f"optional dependency not installed: {exc.name}")
        raise AssertionError(f"{module} has no attribute or submodule {name!r}") from exc


def test_widgets_import_biblium_somewhere():
    assert len(IMPORTS) > 50


@pytest.mark.parametrize("module, name, source", IMPORTS,
                         ids=[f"{s}:{m}.{n}" for m, n, s in IMPORTS])
def test_imported_name_exists(module, name, source):
    if (module, name) in LEGACY:
        pytest.skip("fallback location for older Biblium releases")
    _resolve(module, name)


@pytest.mark.parametrize("module, name", ATTRIBUTES,
                         ids=[f"{m}.{n}" for m, n in ATTRIBUTES])
def test_attribute_exists(module, name):
    _resolve(module, name)


def test_sample_datasets_are_shipped():
    data = os.path.join(os.path.dirname(biblium.__file__), "data")
    for name in ("scopus dataset.csv", "wos dataset.txt", "open alex dataset.csv"):
        assert os.path.exists(os.path.join(data, name)), name


def test_installed_biblium_meets_the_declared_minimum():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "orangebib_sources", os.path.join(PACKAGE, "sources.py"))
    sources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sources)
    assert sources.biblium_is_current(biblium.__version__), (
        f"Biblium {biblium.__version__} is older than {sources.MIN_BIBLIUM}")
