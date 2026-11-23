"""Unit tests for the data-source helpers (OpenAlex ordering, combining databases).

The ordering tests need nothing beyond the standard library. The merge tests
call ``biblium.merge`` and are skipped when Biblium (>= 2.19.1) is not
installed. Neither group needs Orange or Qt.
"""
import importlib.util
import os

import pytest

# Loaded directly from its file so the test runs without Orange/Qt installed:
# importing the ``orangebib`` package would pull in the widget stack.
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "orangebib", "sources.py")
_spec = importlib.util.spec_from_file_location("orangebib_sources", _PATH)
sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sources)


# ---------------------------------------------------------------- ordering --

def test_sort_keys_cover_the_six_orderings():
    assert sources.sort_keys() == ["most_cited", "least_cited", "newest",
                                   "oldest", "relevance", "random"]
    assert all(sources.sort_label(k) for k in sources.sort_keys())


@pytest.mark.parametrize("key, expected", [
    ("most_cited", "cited_by_count:desc"),
    ("least_cited", "cited_by_count:asc"),
    ("newest", "publication_date:desc"),
    ("oldest", "publication_date:asc"),
    ("relevance", "relevance_score:desc"),
    ("random", "random"),
])
def test_sort_value_single_criterion(key, expected):
    assert sources.sort_value(key, has_search=True) == expected


def test_relevance_without_search_falls_back_to_most_cited():
    assert sources.sort_value("relevance", has_search=False) == "cited_by_count:desc"
    assert sources.sort_value(None, has_search=False) == "cited_by_count:desc"


def test_default_sort_keeps_the_previous_behaviour_for_keyword_queries():
    # Before the option existed, a keyword query was returned in OpenAlex's
    # default order for searches, which is relevance.
    assert sources.sort_value(None, has_search=True) == "relevance_score:desc"
    assert sources.sort_value("", "", has_search=True) == "relevance_score:desc"


def test_secondary_criterion_is_appended():
    assert (sources.sort_value("most_cited", "newest")
            == "cited_by_count:desc,publication_date:desc")
    assert (sources.sort_value("relevance", "most_cited", has_search=True)
            == "relevance_score:desc,cited_by_count:desc")


def test_secondary_criterion_is_ignored_when_meaningless():
    # same field as the primary criterion
    assert sources.sort_value("most_cited", "least_cited") == "cited_by_count:desc"
    assert sources.sort_value("newest", "oldest") == "publication_date:desc"
    # random sampling has no ties to break
    assert sources.sort_value("random", "newest") == "random"
    assert sources.sort_value("newest", "random") == "publication_date:desc"
    # empty / placeholder
    assert sources.sort_value("newest", "") == "publication_date:desc"
    assert sources.sort_value("newest", sources.NO_SECONDARY) == "publication_date:desc"
    # relevance fallback must not duplicate the citation field
    assert (sources.sort_value("relevance", "most_cited", has_search=False)
            == "cited_by_count:desc")


def test_raw_openalex_value_is_passed_through():
    assert sources.sort_value("fwci:desc") == "fwci:desc"


def test_secondary_keys_exclude_relevance_and_random():
    keys = sources.secondary_keys()
    assert "relevance" not in keys and "random" not in keys
    assert set(keys) == {"most_cited", "least_cited", "newest", "oldest"}


def test_page_params_sorted_query_uses_cursor():
    first = sources.page_params("cited_by_count:desc", 500, 0, None, 1)
    assert first == {"sort": "cited_by_count:desc", "per_page": 200, "cursor": "*"}
    last = sources.page_params("cited_by_count:desc", 500, 400, "abc", 3)
    assert last == {"sort": "cited_by_count:desc", "per_page": 100, "cursor": "abc"}


def test_page_params_random_uses_sample_seed_and_constant_page_size():
    p1 = sources.page_params("random", 250, 0, "*", 1)
    p2 = sources.page_params("random", 250, 200, "*", 2)
    assert p1 == {"sample": 250, "seed": 42, "per_page": 200, "page": 1}
    # The page size must not shrink on the last page: numbered pages are
    # offsets of per_page records, so a smaller size would repeat records.
    assert p2 == {"sample": 250, "seed": 42, "per_page": 200, "page": 2}
    assert "cursor" not in p1 and "sort" not in p1


def test_page_params_random_respects_the_openalex_sample_limit():
    assert sources.page_params("random", 50_000, 0, None, 1)["sample"] == sources.MAX_SAMPLE


def test_describe_sort():
    assert sources.describe_sort("random") == "random sample (seeded)"
    assert (sources.describe_sort("cited_by_count:desc,publication_date:desc")
            == "most cited first, then newest first")


def test_ordering_tables_match_biblium():
    oa = pytest.importorskip("biblium.openalex_api")
    if not hasattr(oa, "SORT_OPTIONS"):
        pytest.skip("Biblium older than 2.19.1")
    assert sources.SORT_OPTIONS == dict(oa.SORT_OPTIONS)
    assert sources.SORT_LABELS == dict(oa.SORT_LABELS)
    for key in sources.sort_keys():
        for has_search in (True, False):
            assert (sources.sort_value(key, has_search=has_search)
                    == oa.resolve_sort(key, has_search=has_search))


# ----------------------------------------------------------------- API key --

def test_openalex_key_prefers_the_explicit_value(monkeypatch):
    monkeypatch.setenv(sources.OPENALEX_KEY_ENV, "from-env")
    assert sources.openalex_key("  typed  ") == "typed"
    assert sources.openalex_key("") == "from-env"
    assert sources.openalex_key(None) == "from-env"


def test_openalex_key_falls_back_to_the_stored_key(monkeypatch):
    monkeypatch.delenv(sources.OPENALEX_KEY_ENV, raising=False)
    monkeypatch.setattr(sources, "stored_openalex_key", lambda: "stored")
    assert sources.openalex_key("") == "stored"
    monkeypatch.setattr(sources, "stored_openalex_key", lambda: "")
    assert sources.openalex_key("") == ""


def test_openalex_key_travels_in_a_header_not_in_the_url():
    assert sources.openalex_headers("abc") == {"Authorization": "Bearer abc"}
    assert sources.openalex_headers("") == {}
    assert sources.openalex_headers(None) == {}
    # nothing key-related among the query parameters
    for value in ("cited_by_count:desc", "random"):
        params = sources.page_params(value, 100, 0, None, 1)
        assert "api_key" not in params and "mailto" not in params


def test_openalex_auth_error_messages():
    assert sources.openalex_auth_error(200, False) is None
    assert sources.openalex_auth_error(429, True) is None
    missing = sources.openalex_auth_error(401, False)
    assert "requires a free API key" in missing and sources.OPENALEX_KEY_URL in missing
    rejected = sources.openalex_auth_error(403, True)
    assert "rejected the API key" in rejected


# ----------------------------------------------------------------- version --

def test_version_tuple():
    assert sources.version_tuple("2.19.1") == (2, 19, 1)
    assert sources.version_tuple("2.19.1rc1") == (2, 19, 1)
    assert sources.version_tuple("2.19") == (2, 19)
    assert sources.version_tuple(None) == ()


def test_biblium_is_current():
    assert sources.biblium_is_current("2.19.1")
    assert sources.biblium_is_current("2.20.0")
    assert sources.biblium_is_current("3.0")
    assert not sources.biblium_is_current("2.19.0")
    assert not sources.biblium_is_current("2.16.1")
    assert not sources.biblium_is_current("")


# ------------------------------------------------------------------- merge --

@pytest.mark.parametrize("name, expected", [
    ("scopus.csv", "Scopus"),
    ("Scopus_export (3).csv", "Scopus"),
    ("savedrecs.txt", "Web of Science"),
    ("wos dataset.txt", "Web of Science"),
    ("records.txt", "Web of Science"),
    ("open alex dataset.csv", "OpenAlex"),
    ("works-2026-10-30.csv", "OpenAlex"),
    ("pubmed-covid-set.nbib", "PubMed"),
    ("Dimensions-Publication-2026.xlsx", "Dimensions"),
    ("lens-export.csv", "Lens.org"),
    ("my data.csv", None),
])
def test_guess_database(name, expected):
    assert sources.guess_database(os.path.join("some", "folder", name)) == expected
    if expected is not None:
        assert expected in sources.MERGE_DATABASES


def test_combine_needs_two_sources():
    with pytest.raises(ValueError):
        sources.combine_sources([("a.csv", "scopus")])


def test_combine_needs_a_database_for_every_source():
    with pytest.raises(ValueError):
        sources.combine_sources([("a.csv", "scopus"), ("b.csv", "")])


def _frames():
    pd = pytest.importorskip("pandas")
    scopus = pd.DataFrame({
        "Title": ["Alpha study", "Beta study", "Gamma study"],
        "DOI": ["10.1/a", "10.1/b", None],
        "Year": [2020, 2021, 2022],
        "Cited by": [10, 5, 1],
        "Author Keywords": ["x; y", "y", "z"],
        "EID": ["e1", "e2", "e3"],
    })
    wos = pd.DataFrame({
        "Title": ["Alpha study", "Delta study", "Gamma  Study!"],
        "DOI": ["https://doi.org/10.1/A", "10.1/d", None],
        "Year": [2020, 2019, 2022],
        "Cited by": [12, 7, 2],
        "Author Keywords": ["y; w", "v", "z"],
        "UT": ["w1", "w2", "w3"],
    })
    return scopus, wos


def test_combine_by_doi_union():
    pytest.importorskip("biblium.merge")
    scopus, wos = _frames()
    merged, report = sources.combine_sources(
        [(scopus, "Scopus"), (wos, "Web of Science")], key="doi", columns="union")
    # 10.1/a is shared (DOI spelling and case are normalised); the two records
    # without DOI cannot be matched by DOI and are both kept.
    assert len(merged) == 5
    assert report["n_input"] == {"scopus": 3, "wos": 3}
    assert report["n_removed"] == 1
    shared = merged[merged["DOI"] == "10.1/a"].iloc[0]
    assert shared["Source DB"] == "scopus; wos"
    assert shared["N sources"] == 2
    assert shared["Cited by"] == 12            # maximum over the sources
    assert shared["Cited by (scopus)"] == 10   # per-source counts are kept
    assert shared["Cited by (wos)"] == 12
    assert shared["Author Keywords"] == "x; y; w"   # union, in order
    assert {"EID", "UT"} <= set(merged.columns)     # union of columns


def test_combine_by_doi_then_title_matches_records_without_doi():
    pytest.importorskip("biblium.merge")
    scopus, wos = _frames()
    merged, report = sources.combine_sources(
        [(scopus, "scopus"), (wos, "wos")], key="doi_title")
    assert len(merged) == 4
    assert report["n_removed"] == 2
    assert report["n_without_key"] == 0


def test_combine_intersection_keeps_only_shared_columns():
    pytest.importorskip("biblium.merge")
    scopus, wos = _frames()
    merged, report = sources.combine_sources(
        [(scopus, "scopus"), (wos, "wos")], columns="intersection")
    assert "EID" not in merged.columns and "UT" not in merged.columns
    assert {"Title", "DOI", "Year", "Cited by", "Author Keywords"} <= set(merged.columns)
    assert set(report["columns_dropped"]) == {"EID", "UT"}


def test_merge_summary():
    pytest.importorskip("biblium.merge")
    scopus, wos = _frames()
    _, report = sources.combine_sources(
        [(scopus, "scopus"), (wos, "wos")], columns="intersection")
    text = sources.merge_summary(report)
    assert "6 records from 2 sources" in text
    assert "5 unique" in text and "1 duplicates merged" in text
    assert "2 records had no matching key" in text
    assert "2 source-specific columns dropped" in text


def test_combine_bundled_sample_files():
    """End to end on the three sample exports shipped with Biblium."""
    biblium = pytest.importorskip("biblium")
    pytest.importorskip("biblium.merge")
    data = os.path.join(os.path.dirname(biblium.__file__), "data")
    files = [(os.path.join(data, "scopus dataset.csv"), "Scopus"),
             (os.path.join(data, "wos dataset.txt"), "Web of Science"),
             (os.path.join(data, "open alex dataset.csv"), "OpenAlex")]
    if not all(os.path.exists(f) for f, _ in files):
        pytest.skip("Biblium sample files not found")
    merged, report = sources.combine_sources(files, key="doi", columns="union")
    assert report["n_input_total"] == sum(report["n_input"].values())
    assert report["n_output"] == len(merged) == report["n_input_total"] - report["n_removed"]
    assert report["n_removed"] > 0
    assert int(report["overlap"]["Records"].sum()) == len(merged)
    assert merged["Merge key"].is_unique
    narrow, _ = sources.combine_sources(files, key="doi", columns="intersection")
    assert len(narrow) == len(merged)
    assert set(narrow.columns) < set(merged.columns)
