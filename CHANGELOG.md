# Changelog

## 0.4.0
Follows Biblium 2.19.1, which is now the minimum required version.

### New
- Bibliographic Data, **Combine** tab: combine exports from several databases
  (Scopus, Web of Science, OpenAlex, PubMed, Dimensions, Lens.org) into one
  de-duplicated dataset through `biblium.merge`. Matching by DOI, by DOI with
  title fallback, or by title; union or intersection of columns; provenance
  columns `Source DB`, `N sources`, `Merge key`, `Match type`; new output
  **Source Overlap**.
- Bibliographic Data, **API** tab: **Order by** (most cited, least cited,
  newest, oldest, relevance, seeded random sample) and an optional **Then by**
  criterion decide which records are returned when a query matches more
  records than *Max Results*.
- `orangebib.sources`: the logic of both features, free of Orange and Qt,
  with unit tests in `tests/test_sources.py`.

- `examples/benchmark_scalability.py`: run time and peak memory of the
  widgets' operations on corpora of increasing size.
- `tests/test_biblium_contract.py`: checks every Biblium name the widgets
  import against the installed Biblium, so an upstream rename fails the test
  suite instead of silently disabling a feature.
- Continuous integration also runs weekly against the newest Orange and
  Biblium releases.

### Changed
- Requires `biblium>=2.19.1` and Python 3.10 or newer (Biblium 2.19 dropped
  Python 3.9). Installing or upgrading the add-on upgrades Biblium; the
  Bibliographic Data widget warns when an older Biblium is still installed.
- OpenAlex queries without a search string (author, institution, journal, DOI
  list) are now returned most cited first by default; previously their order
  was left to OpenAlex. Keyword queries keep the relevance order.

### Fixed
- `examples/reproduce_figures.py` reported differences that were not
  differences in results: rows with equal sort values in another order, and
  Monte Carlo permutation p-values differing in the third decimal. Tables are
  now compared as sets of rows and permutation p-values within their sampling
  error; every deterministic quantity must still agree within 1e-6.
- OpenAlex has required an API key for all requests since 13 February 2026
  and ignores the `mailto` parameter; queries beyond the first page were
  refused with HTTP 401. Bibliographic Data, OpenAlex Enrichment and OA
  Finder now have an **OpenAlex API key** field. The key is kept in the
  system credential store (or read from the `OPENALEX_API_KEY` environment
  variable), is sent as a request header, and is not written into workflow
  files. A refused request now explains how to obtain a key.
- OA Finder reported every document as not found when OpenAlex refused the
  request; it now reports the refusal.
- Permutation Test did not run with Biblium 2.19, and the Firth
  option of Logistic Regression was disabled: both imported modules that
  Biblium has since merged into `biblium.utilsbib`. The widgets now use the
  new location and fall back to the old one.

## 0.2.0
- 81 widgets spanning the full bibliometric pipeline.
- New: Deduplicate & Merge, Discipline Analysis, Field Networks, Topic Modeling, HTML Dashboard.
- Logistic Regression: Firth penalised option; multi-target tabs + summary pivot.
- Plot Bibliometric Network: VOSviewer-style density views, cluster selection, aesthetics.
- Documentation scaffold (README + Sphinx).
