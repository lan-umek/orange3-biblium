# -*- coding: utf-8 -*-
"""
Data-source helpers for Orange3-Biblium.
========================================

Qt-free logic behind two features of the *Bibliographic Data* widget that
follow Biblium 2.19.1:

- **Result ordering for OpenAlex queries** (``sort_value``, ``page_params``).
  When only a subset of the matching records is downloaded, the ordering
  decides *which* records are returned: most cited, least cited, newest,
  oldest, by search relevance, or a seeded random sample. An optional
  secondary criterion breaks ties.
- **OpenAlex API key** (``openalex_key``, ``openalex_headers``). OpenAlex has
  required a free API key for all requests since 13 February 2026 and ignores
  the former ``mailto`` parameter. The key is read from the widget, from the
  ``OPENALEX_API_KEY`` environment variable or from the system credential
  store, and is sent as a request header so that it never appears in a URL,
  an error message or a saved workflow.
- **Combining exports from several databases** (``combine_sources``), a thin
  wrapper over ``biblium.merge.combine_databases``: records are matched by
  DOI, by normalised title, or by DOI with title fallback; duplicates are
  merged; the result keeps either all columns (union) or only the columns
  shared by every source (intersection).

The module depends only on pandas (and on Biblium for the merge), holds no
Orange or Qt state, and is covered by ``tests/test_sources.py``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Oldest Biblium release that provides ``biblium.merge`` and the OpenAlex
#: ordering helpers; also the minimum declared in ``setup.py``.
MIN_BIBLIUM = "2.19.1"

# -----------------------------------------------------------------------------
# OpenAlex result ordering
# -----------------------------------------------------------------------------

# Fallback copies of the Biblium tables, used only when Biblium is missing or
# older than 2.19.1, so the widget still orders results the same way.
_SORT_OPTIONS: Dict[str, str] = {
    "most_cited": "cited_by_count:desc",
    "least_cited": "cited_by_count:asc",
    "newest": "publication_date:desc",
    "oldest": "publication_date:asc",
    "relevance": "relevance_score:desc",
    "random": "random",
}
_SORT_LABELS: Dict[str, str] = {
    "most_cited": "Most cited first",
    "least_cited": "Least cited first",
    "newest": "Newest first",
    "oldest": "Oldest first",
    "relevance": "Relevance (search string)",
    "random": "Random sample",
}
_MAX_SAMPLE = 10_000

try:  # single source of truth is Biblium
    from biblium.openalex_api import (  # noqa: PLC0415
        MAX_SAMPLE, SORT_LABELS, SORT_OPTIONS,
    )
    SORT_OPTIONS = dict(SORT_OPTIONS)
    SORT_LABELS = dict(SORT_LABELS)
except Exception:  # noqa: BLE001 - Biblium absent or older than 2.19.1
    SORT_OPTIONS, SORT_LABELS, MAX_SAMPLE = dict(_SORT_OPTIONS), dict(_SORT_LABELS), _MAX_SAMPLE

#: Ordering used when a stored workflow has no ordering setting. With a search
#: string this is what OpenAlex returned before the option existed.
DEFAULT_SORT = "relevance"
#: Label of the "no secondary criterion" entry.
NO_SECONDARY = "(none)"


def sort_keys() -> List[str]:
    """Ordering keys in display order."""
    return list(SORT_OPTIONS)


def sort_label(key: str) -> str:
    return SORT_LABELS.get(key, key)


def secondary_keys() -> List[str]:
    """Keys usable as a tie-breaker (everything except relevance and random)."""
    return [k for k in SORT_OPTIONS if k not in ("relevance", "random")]


def _field(value: str) -> str:
    return value.split(":", 1)[0]


def sort_value(primary: Optional[str], secondary: Optional[str] = None,
               has_search: bool = True) -> str:
    """Return the OpenAlex ``sort`` value for the chosen ordering.

    ``primary`` and ``secondary`` are ``SORT_OPTIONS`` keys (a raw OpenAlex
    value such as ``"fwci:desc"`` is passed through). ``"random"`` is returned
    as is and means seeded random sampling. Relevance needs a search string;
    without one it falls back to most cited first, as in Biblium. A secondary
    criterion on a different field is appended after a comma; it is ignored
    for random sampling and when it repeats the primary field.
    """
    key = (primary or DEFAULT_SORT).strip()
    value = SORT_OPTIONS.get(key, key)
    if value == "random":
        return "random"
    if value.startswith("relevance_score") and not has_search:
        value = SORT_OPTIONS["most_cited"]
    if secondary and secondary != NO_SECONDARY:
        second = SORT_OPTIONS.get(secondary.strip(), secondary.strip())
        if (second != "random"
                and not (second.startswith("relevance_score") and not has_search)
                and _field(second) not in {_field(v) for v in value.split(",")}):
            value = f"{value},{second}"
    return value


def page_params(value: str, n_wanted: int, got: int, cursor: Optional[str],
                page: int, per_page: int = 200, seed: int = 42) -> Dict[str, Any]:
    """Request parameters for the next page of results.

    Sorted queries use cursor pagination. Random sampling uses OpenAlex
    ``sample`` with a fixed ``seed`` and numbered pages, because ``sample``
    cannot be combined with a cursor; the seed makes the sample repeatable.
    """
    if value == "random":
        # Numbered pages are offsets of ``per_page`` records, so the page size
        # must stay constant; the caller discards any surplus on the last page.
        return {"sample": min(n_wanted, MAX_SAMPLE), "seed": seed,
                "per_page": per_page, "page": page}
    size = max(1, min(per_page, n_wanted - got))
    return {"sort": value, "per_page": size, "cursor": cursor or "*"}


def describe_sort(value: str) -> str:
    """Short human-readable description of a ``sort_value`` result."""
    if value == "random":
        return "random sample (seeded)"
    names = {v: SORT_LABELS.get(k, k).lower() for k, v in SORT_OPTIONS.items()}
    return ", then ".join(names.get(part, part) for part in value.split(","))


# -----------------------------------------------------------------------------
# OpenAlex API key
# -----------------------------------------------------------------------------

OPENALEX_KEY_ENV = "OPENALEX_API_KEY"
OPENALEX_KEY_URL = "https://openalex.org/settings/api"
OPENALEX_KEY_HINT = (
    "OpenAlex requires a free API key (since February 2026). Create an "
    f"account at openalex.org, copy the key from {OPENALEX_KEY_URL} and "
    "enter it in the 'OpenAlex API key' field."
)
_CREDENTIAL_SERVICE = "OpenAlex"


def stored_openalex_key() -> str:
    """Key kept in the system credential store (through Orange), or ''."""
    try:
        from Orange.widgets.credentials import CredentialManager  # noqa: PLC0415
        return (CredentialManager(_CREDENTIAL_SERVICE).api_key or "").strip()
    except Exception:  # noqa: BLE001 - no Orange, no keyring backend, ...
        return ""


def store_openalex_key(key: str) -> bool:
    """Save (or, for an empty key, remove) the key in the credential store.

    The key is kept outside Orange's widget settings on purpose: settings are
    written into workflow files, which are routinely shared.
    """
    try:
        from Orange.widgets.credentials import CredentialManager  # noqa: PLC0415
        manager = CredentialManager(_CREDENTIAL_SERVICE)
        key = (key or "").strip()
        if key:
            manager.api_key = key
        else:
            try:
                del manager.api_key
            except Exception:  # noqa: BLE001 - nothing was stored
                pass
        return True
    except Exception:  # noqa: BLE001
        return False


def openalex_key(explicit: Optional[str] = None) -> str:
    """The key to use: the one given, else the environment variable, else
    the stored one. Returns '' when none is available."""
    key = (explicit or "").strip()
    if key:
        return key
    key = os.environ.get(OPENALEX_KEY_ENV, "").strip()
    return key or stored_openalex_key()


def openalex_headers(key: Optional[str]) -> Dict[str, str]:
    """Request headers carrying the key (empty when there is no key)."""
    key = (key or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def openalex_auth_error(status_code: int, has_key: bool) -> Optional[str]:
    """Message for an authentication failure, or None for other statuses."""
    if status_code not in (401, 403):
        return None
    if has_key:
        return (f"OpenAlex rejected the API key (HTTP {status_code}). Check "
                f"the key at {OPENALEX_KEY_URL}; the free plan also has a "
                "daily usage limit.")
    return f"HTTP {status_code}: {OPENALEX_KEY_HINT}"


# -----------------------------------------------------------------------------
# Combining exports from several databases
# -----------------------------------------------------------------------------

#: Label shown in the widget -> Biblium database key.
MERGE_DATABASES: Dict[str, str] = {
    "Scopus": "scopus",
    "Web of Science": "wos",
    "OpenAlex": "oa",
    "PubMed": "pubmed",
    "Dimensions": "dimensions",
    "Lens.org": "lens",
}
#: Label -> ``key`` argument of ``combine_databases``.
MATCH_KEYS: Dict[str, str] = {
    "DOI": "doi",
    "DOI, then title for records without DOI": "doi_title",
    "Title": "title",
}
#: Label -> ``columns`` argument of ``combine_databases``.
COLUMN_POLICIES: Dict[str, str] = {
    "All columns (union)": "union",
    "Only columns shared by all sources (intersection)": "intersection",
}


def version_tuple(version: Optional[str]) -> Tuple[int, ...]:
    """``"2.19.1"`` -> ``(2, 19, 1)``; non-numeric suffixes are ignored."""
    parts = []
    for piece in str(version or "").split("."):
        m = re.match(r"\d+", piece)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def biblium_version() -> Optional[str]:
    """Installed Biblium version, or None when Biblium cannot be imported."""
    try:
        import biblium  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    return getattr(biblium, "__version__", None)


def biblium_is_current(version: Optional[str] = None) -> bool:
    """True when the installed Biblium is at least ``MIN_BIBLIUM``."""
    if version is None:
        version = biblium_version()
    return bool(version) and version_tuple(version) >= version_tuple(MIN_BIBLIUM)


def guess_database(path: str) -> Optional[str]:
    """Guess the ``MERGE_DATABASES`` label of an export from its file name.

    Only the file name and extension are inspected, so the result is a
    starting value for the user to confirm, not a detection.
    """
    name = os.path.basename(str(path)).lower()
    ext = os.path.splitext(name)[1]
    hints = [
        ("Scopus", ("scopus",)),
        ("Web of Science", ("wos", "savedrecs", "web of science", "webofscience")),
        ("OpenAlex", ("openalex", "open alex", "open_alex", "works-")),
        ("PubMed", ("pubmed", "medline")),
        ("Dimensions", ("dimensions",)),
        ("Lens.org", ("lens",)),
    ]
    for label, words in hints:
        if any(w in name for w in words):
            return label
    if ext == ".nbib":
        return "PubMed"
    if ext == ".txt":
        return "Web of Science"
    return None


def combine_sources(sources: Sequence[Tuple[Any, str]], key: str = "doi",
                    columns: str = "union", **kwargs):
    """Combine and de-duplicate exports from several databases.

    ``sources`` is a list of ``(path_or_DataFrame, database)`` pairs, where
    ``database`` is a Biblium key (``"scopus"``, ``"wos"``, ``"oa"``, ...) or
    a ``MERGE_DATABASES`` label. Returns ``(merged, report)`` exactly as
    ``biblium.merge.combine_databases`` does: the merged frame uses the
    Scopus-like column names and the ``"; "`` separator, and carries the
    provenance columns ``Source DB``, ``N sources``, ``Merge key`` and
    ``Match type``.
    """
    pairs = [(item, MERGE_DATABASES.get(db, db)) for item, db in sources]
    if len(pairs) < 2:
        raise ValueError("Select at least two sources to combine")
    if any(not db for _, db in pairs):
        raise ValueError("Choose the database of every source")
    try:
        from biblium.merge import combine_databases  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Combining databases needs biblium>={MIN_BIBLIUM} "
            f"(installed: {biblium_version() or 'none'}). "
            f"Upgrade with: pip install -U biblium"
        ) from exc
    return combine_databases(pairs, key=key, columns=columns, **kwargs)


def merge_summary(report: Dict[str, Any]) -> str:
    """One-paragraph summary of a ``combine_databases`` report."""
    n_input = report.get("n_input", {})
    per_source = ", ".join(f"{db}: {n:,}" for db, n in n_input.items())
    text = (f"{report.get('n_input_total', 0):,} records from {len(n_input)} sources "
            f"({per_source}) → {report.get('n_output', 0):,} unique; "
            f"{report.get('n_removed', 0):,} duplicates merged")
    no_key = report.get("n_without_key", 0)
    if no_key:
        text += f"; {no_key:,} records had no matching key and were kept as they are"
    dropped = report.get("columns_dropped") or []
    if dropped:
        text += f"; {len(dropped)} source-specific columns dropped"
    return text + "."
