#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Performance and scalability benchmark for Orange3-Biblium.

Measures run time and peak memory of the operations the widgets perform, on
corpora of increasing size, and writes the results as tables. Like
``reproduce_figures.py`` it calls the methods the widgets call, without a
graphical session, so the figures describe the add-on's computations rather
than the speed of drawing them.

Corpora
-------
The 613-record OpenAlex sample shipped with Biblium is the smallest corpus.
Larger corpora are built by drawing records from that file at random, with
replacement and a fixed seed, and writing them to a file in the same export
format. Import is therefore timed on a real file of the stated size. Because
the records are resampled, the number of distinct authors, keywords and
sources does not grow with the corpus, whereas in real data it does: the
timings show how the operations scale with the number of documents, and are
optimistic for operations whose cost depends on the number of distinct
entities.

Operations
----------
import            read the export file with Biblium (``BiblioAnalysis``)
table_conversion  pandas -> Orange Table -> pandas, the channel between widgets
group_assoc       Group Associations: contingency table, chi-square with the
                  per-entity permutation test (999 permutations) and
                  correspondence analysis; keywords x three periods
entity_relations  Entity Relationships: co-occurrence matrix, chi-square,
                  correspondence analysis and association measures;
                  authors x keywords
network_keywords  Network Co-occurrence: author-keyword network
network_coauthors Network Co-occurrence: co-authorship network
permutation_test  Permutation Test widget: omnibus chi-square permutation
                  test (``biblium.utilsbib.assoc_permutation_test``)
dynamic_topics    Dynamic Topics: sequential LDA over publication periods
openalex_fetch    (only with --online) Bibliographic Data: download N records
                  from the OpenAlex API

Method
------
Before anything is timed, every operation is called once on the smallest
corpus and the result discarded: the first call in a session also loads
libraries and language resources, which is a fixed cost of starting up and
not a property of the operation. Each operation is then run once for timing;
operations that finish within five seconds are run three times and the median
is reported. Besides seconds, run time is given relative to the smallest
corpus (= 100), next to the corpus size on the same scale, so that the growth
of each operation can be compared with the growth of the data. Two memory figures
are recorded. *Process peak* is the largest amount of memory the whole Python
process held while the operation ran (sampled every 20 ms); it includes the
corpus and the loaded libraries and is what the computer must provide.
*Allocated peak* is measured in a separate run with ``tracemalloc`` and is the
memory the operation itself allocated through Python and NumPy; memory
allocated by other native libraries is not included in it. An operation that
exceeds ``--max-seconds`` is not attempted on larger corpora.

Usage
-----
    python examples/benchmark_scalability.py
    python examples/benchmark_scalability.py --sizes 613 1000 5000
    python examples/benchmark_scalability.py --online

``--online`` needs an OpenAlex API key (free, https://openalex.org/settings/api).
It is read from the ``OPENALEX_API_KEY`` environment variable or from the key
saved through the Bibliographic Data widget, and is never written to the
result files.

Results are written to ``examples/benchmark/``: ``results.csv`` (one row per
operation and corpus size), ``summary_time.csv``,
``summary_time_relative.csv`` (smallest corpus = 100),
``summary_memory_process.csv`` and ``summary_memory_allocated.csv``
(operations x sizes) and ``environment.json`` (hardware and versions).
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "benchmark")
sys.path.insert(0, ROOT)

DEFAULT_SIZES = [613, 1000, 2500, 5000, 10000, 25000, 50000]
ONLINE_SIZES = [200, 1000, 5000, 10000]
SEED = 42

# Widget settings used throughout (larger than the paper's figures, to load
# the analytical steps more heavily).
TOP_N = 50            # entities per axis
MIN_FREQ = 5
NETWORK_NODES = 100
N_PERMUTATIONS = 999
N_TOPICS, PERIOD_SIZE = 10, 5
PERIOD_CUTS = (2008, 2014)


def _shim(cls, **attrs):
    """A plain object carrying the widget class's own methods (see
    ``reproduce_figures.py``): runs the widget's code without any Qt object."""
    namespace = {k: v for k, v in vars(cls).items() if not k.startswith("__")}
    obj = type(cls.__name__ + "Shim", (), namespace)()
    obj.__dict__.update(attrs)
    return obj


# ------------------------------------------------------------------ corpora --

def sample_path() -> str:
    try:
        import biblium
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit("biblium is required: pip install Orange3-Biblium") from exc
    path = os.path.join(os.path.dirname(biblium.__file__), "data",
                        "open alex dataset.csv")
    if not os.path.exists(path):
        raise SystemExit(f"sample dataset not found: {path}")
    return path


def make_corpus_file(raw: pd.DataFrame, n: int, folder: str, original: str) -> str:
    """Return the path of an export file with *n* records."""
    if n == len(raw):
        return original
    rows = np.random.default_rng(SEED).integers(0, len(raw), size=n)
    path = os.path.join(folder, f"openalex_resampled_{n}.csv")
    raw.iloc[rows].to_csv(path, index=False)
    return path


def available_memory_mb():
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 20
    except Exception:  # noqa: BLE001 - psutil is optional
        return None


# -------------------------------------------------------------- measurement --

def process_memory_mb():
    """Memory currently held by this process (resident set), or None."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2 ** 20
    except Exception:  # noqa: BLE001 - psutil is optional
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD),
                            ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            get_info = kernel32.K32GetProcessMemoryInfo
            get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return counters.WorkingSetSize / 2 ** 20
        except Exception:  # noqa: BLE001
            return None
        return None
    try:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 20
    except Exception:  # noqa: BLE001 - e.g. macOS without psutil
        return None


class MemoryWatch:
    """Samples the process memory every 20 ms while a block runs."""

    def __enter__(self):
        self.peak = process_memory_mb()
        self._stop = threading.Event()
        self._thread = None
        if self.peak is not None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(0.02):
            now = process_memory_mb()
            if now is not None and now > self.peak:
                self.peak = now

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            now = process_memory_mb()
            if now is not None and now > self.peak:
                self.peak = now
        return False


def measure(func, max_mem_pass_seconds: float):
    """Run *func*; return (seconds, memory, runs, result, error).

    ``memory`` is ``(process_peak_mb, python_peak_mb)``: the largest amount of
    memory the whole process held while the operation ran, and the memory the
    operation itself allocated through Python and NumPy.
    """
    gc.collect()
    try:
        with MemoryWatch() as watch:
            t0 = time.perf_counter()
            result = func()
            times = [time.perf_counter() - t0]
    except MemoryError:
        return None, (None, None), 0, None, "MemoryError"
    except Exception as exc:  # noqa: BLE001 - recorded, the run continues
        return None, (None, None), 0, None, f"{type(exc).__name__}: {exc}"[:300]
    if times[0] < 5.0:
        for _ in range(2):
            t0 = time.perf_counter()
            func()
            times.append(time.perf_counter() - t0)
    seconds = statistics.median(times)

    peak_mb = None
    if seconds <= max_mem_pass_seconds:
        gc.collect()
        tracemalloc.start()
        try:
            func()
            peak_mb = tracemalloc.get_traced_memory()[1] / 2 ** 20
        except Exception:  # noqa: BLE001
            peak_mb = None
        finally:
            tracemalloc.stop()
    return seconds, (watch.peak, peak_mb), len(times), result, ""


# --------------------------------------------------------------- operations --

def resolve(df: pd.DataFrame, key: str) -> str:
    from orangebib.base import COLUMN_PATTERNS, find_column

    col = find_column(df, COLUMN_PATTERNS[key])
    if col is None:
        raise KeyError(f"column for {key!r} not found")
    return col


def period_groups(df: pd.DataFrame) -> pd.DataFrame:
    year = pd.to_numeric(df[resolve(df, "year")], errors="coerce")
    lo, hi = PERIOD_CUTS
    return pd.DataFrame({
        f"-{lo}": (year <= lo).astype(int),
        f"{lo + 1}-{hi}": ((year > lo) & (year <= hi)).astype(int),
        f"{hi + 1}-": (year > hi).astype(int),
    }, index=df.index)


def op_import(path: str):
    from biblium import BiblioAnalysis

    return BiblioAnalysis(path, db="oa", res_folder=None, verbose=False).df


def op_table_conversion(df: pd.DataFrame):
    from orangebib.base import df_to_table, table_to_df

    return table_to_df(df_to_table(df)).shape


_CACHE: dict = {}     # per-corpus inputs shared by operations; cleared per size


def _group_assoc_inputs(df: pd.DataFrame):
    from orangebib.widgets.owgroupassociations import OWGroupAssociations

    w = _shim(OWGroupAssociations, min_freq=MIN_FREQ, top_n=TOP_N)
    gm = period_groups(df)
    groups = list(gm.columns)
    label, col = "Keyword", resolve(df, "keywords")
    sep = w._detect_separator(df)
    cont = w._build_contingency(df, gm, groups, col, label, "list", sep)
    if cont.empty:
        raise ValueError("empty contingency table")
    items = cont[label].tolist()
    P, Gmat = w._doc_level_matrices(df, gm, groups, col, items, "list", sep)
    return w, cont, groups, label, items, P, Gmat


def op_group_assoc(df: pd.DataFrame):
    inputs = _group_assoc_inputs(df)      # building the tables is part of the step
    _CACHE["group_assoc"] = inputs
    w, cont, groups, label, items, P, Gmat = inputs
    mat = cont[groups].values.astype(float)
    w._calc_chi_square(mat, items, groups, label, P, Gmat)
    w._calc_ca(mat, items, groups, label)
    return f"{mat.shape[0]} x {mat.shape[1]}"


def op_entity_relations(df: pd.DataFrame):
    from orangebib.widgets.owentityrelations import OWEntityRelations

    w = _shim(
        OWEntityRelations,
        row_min_freq=MIN_FREQ, col_min_freq=MIN_FREQ,
        row_top_n=TOP_N, col_top_n=TOP_N,
        row_max_items=0, col_max_items=0,
        row_include_text="", col_include_text="",
        row_exclude_text="", col_exclude_text="",
        row_regex_include="", col_regex_include="",
        row_regex_exclude="", col_regex_exclude="",
    )
    rows_col, cols_col = resolve(df, "authors"), resolve(df, "keywords")
    sep = w._detect_separator(df)
    row_items = w._get_filtered_entities(df, rows_col, "list", sep, "row")
    col_items = w._get_filtered_entities(df, cols_col, "list", sep, "col")
    if not row_items or not col_items:
        raise ValueError("no entities passed the filters")
    cooc = w._build_cooccurrence(df, rows_col, cols_col, "list", "list",
                                 row_items, col_items, sep)
    row_items = cooc["Row"].tolist()
    mat = cooc[col_items].values.astype(float)
    w._calc_chi_square(mat, row_items, col_items)
    w._calc_ca(mat, row_items, col_items)
    w._calc_associations(mat, row_items, col_items)
    return f"{mat.shape[0]} x {mat.shape[1]}"


def op_network(df: pd.DataFrame, network_type: str):
    from orangebib.widgets.ownetworkcooccurrence import NetworkBuilder

    nodes, matrix, props = NetworkBuilder(df, list(df.columns)).build(
        network_type, top_n=NETWORK_NODES, min_occ=2, min_edge=1)
    if isinstance(props, dict) and props.get("error"):
        raise ValueError(props["error"])
    edges = int((np.asarray(matrix) > 0).sum() // 2) if len(nodes) else 0
    return f"{len(nodes)} nodes, {edges} edges"


def op_permutation_test(df: pd.DataFrame):
    from biblium import utilsbib

    # The indicator matrices are the widget's inputs, so preparing them is
    # not part of the timed test when they are already available.
    if "group_assoc" not in _CACHE:
        _CACHE["group_assoc"] = _group_assoc_inputs(df)
    _, _, groups, _, items, P, Gmat = _CACHE["group_assoc"]
    gdf = pd.DataFrame(Gmat, columns=groups)
    edf = pd.DataFrame(P, columns=items)
    res = utilsbib.assoc_permutation_test(
        gdf, edf, test="chi2", n_permutations=N_PERMUTATIONS,
        random_state=SEED, show_progress=False, warn_disjoint=False)
    return f"{res.n_permutations} permutations"


def op_dynamic_topics(df: pd.DataFrame):
    from biblium.addons.dynamic_topic_models import analyze_dynamic_topics

    res = analyze_dynamic_topics(
        df, text_column=resolve(df, "abstract"), year_column=resolve(df, "year"),
        method="sequential_lda", n_topics=N_TOPICS, period_size=PERIOD_SIZE)
    return f"{len(res.topic_evolutions or {})} topics"


def op_openalex_fetch(n: int, query: str, email: str):
    from orangebib.widgets.owbibliographicdata import FetchWorker
    # The worker finds the key itself (environment variable or stored key).

    worker = FetchWorker({
        "query": query, "search_type": "Keywords",
        "year_from": 1990, "year_to": time.gmtime().tm_year,
        "doc_type": None, "max_results": n, "open_access": False,
        "email": email, "sort": "most_cited", "sort_secondary": "",
    })
    out = {}
    worker.finished.connect(lambda df, err: out.update(df=df, err=err))
    worker.run()            # synchronous: the thread is not started
    if out.get("err"):
        raise RuntimeError(out["err"])
    got = 0 if out.get("df") is None else len(out["df"])
    if got == 0:
        raise RuntimeError("no records returned")
    return f"{got} records"


LOCAL_OPS = [
    ("table_conversion", op_table_conversion),
    ("group_assoc", op_group_assoc),
    ("entity_relations", op_entity_relations),
    ("network_keywords", lambda df: op_network(df, "author_keywords")),
    ("network_coauthors", lambda df: op_network(df, "coauthorship")),
    ("permutation_test", op_permutation_test),
    ("dynamic_topics", op_dynamic_topics),
]


# --------------------------------------------------------------- environment --

def environment() -> dict:
    env = {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "date_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
    }
    try:
        import psutil
        env["ram_gb"] = round(psutil.virtual_memory().total / 2 ** 30, 1)
        env["cpu_physical"] = psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001
        env["ram_gb"] = None
    for name in ("Orange", "biblium", "orangebib", "numpy", "pandas", "scipy",
                 "sklearn", "networkx"):
        try:
            env[name] = getattr(__import__(name), "__version__", "?")
        except Exception:  # noqa: BLE001
            env[name] = None
    return env


# --------------------------------------------------------------------- main --

def fmt_seconds(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    return f"{x:.3f}" if x < 1 else (f"{x:.2f}" if x < 10 else f"{x:.1f}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run time and peak memory of Orange3-Biblium operations "
                    "on corpora of increasing size.")
    parser.add_argument("--sizes", type=int, nargs="+", default=DEFAULT_SIZES,
                        help="corpus sizes (number of records)")
    parser.add_argument("--max-seconds", type=float, default=900.0,
                        help="an operation slower than this is not attempted "
                             "on larger corpora (default 900)")
    parser.add_argument("--mem-pass-seconds", type=float, default=300.0,
                        help="skip the separate memory run for operations "
                             "slower than this (default 300)")
    parser.add_argument("--skip", nargs="*", default=[],
                        help="operations to leave out, e.g. dynamic_topics")
    parser.add_argument("--online", action="store_true",
                        help="also time downloads from the OpenAlex API")
    parser.add_argument("--online-sizes", type=int, nargs="+", default=ONLINE_SIZES)
    parser.add_argument("--query", default="bibliometrics",
                        help="search string for --online")
    parser.add_argument("--email", default="",
                        help="e-mail for the OpenAlex polite pool (--online)")
    args = parser.parse_args()

    os.makedirs(OUT, exist_ok=True)
    env = environment()
    with open(os.path.join(OUT, "environment.json"), "w", encoding="utf-8") as fh:
        json.dump(env, fh, indent=2)
    print("Environment:", json.dumps(env))

    original = sample_path()
    raw = pd.read_csv(original, low_memory=False)
    file_mb_per_record = os.path.getsize(original) / 2 ** 20 / len(raw)
    sizes = sorted(set(args.sizes))

    rows = []
    stopped = {}          # operation -> reason it is no longer attempted

    def record(op, n, seconds, memory, runs, note, error):
        process_peak, python_peak = memory or (None, None)
        rows.append({"operation": op, "records": n, "seconds": seconds,
                     "process_peak_mb": process_peak,
                     "allocated_peak_mb": python_peak, "timing_runs": runs,
                     "output": note, "error": error})
        shown = error or f"{fmt_seconds(seconds)} s" + (
            f", process {process_peak:,.0f} MB" if process_peak is not None else "") + (
            f", allocated {python_peak:,.0f} MB" if python_peak is not None else "") + (
            f"  [{note}]" if note else "")
        print(f"  {op:<18} {shown}", flush=True)
        pd.DataFrame(rows).to_csv(os.path.join(OUT, "results.csv"), index=False)

    with tempfile.TemporaryDirectory(prefix="orangebib_bench_") as folder:
        for n in sizes:
            print(f"\n=== {n:,} records ===", flush=True)
            file_mb = file_mb_per_record * n
            free = available_memory_mb()
            # Reading a wide export needs several times its size in memory.
            if free is not None and file_mb * 8 > free:
                reason = (f"skipped: a {file_mb:,.0f} MB file needs more memory "
                          f"than the {free:,.0f} MB available")
                record("import", n, None, None, 0, "", reason)
                break
            if "import" in stopped:
                record("import", n, None, None, 0, "", stopped["import"])
                break
            path = make_corpus_file(raw, n, folder, original)
            if n == sizes[0]:
                # Untimed warm-up: the first call of a session also loads
                # libraries and language resources.
                print("  (warm-up calls, not timed)", flush=True)
                try:
                    warm = op_import(path)
                    for op, func in LOCAL_OPS:
                        if op not in args.skip:
                            try:
                                func(warm)
                            except Exception:  # noqa: BLE001 - reported when timed
                                pass
                    del warm
                except Exception:  # noqa: BLE001
                    pass
                _CACHE.clear()
            seconds, peak, runs, df, error = measure(
                lambda: op_import(path), args.mem_pass_seconds)
            record("import", n, seconds, peak, runs,
                   f"{file_mb:,.1f} MB file" if not error else "", error)
            if error:
                break
            if seconds > args.max_seconds:
                stopped["import"] = f"skipped: exceeded {args.max_seconds:.0f} s at a smaller size"

            _CACHE.clear()
            for op, func in LOCAL_OPS:
                if op in args.skip:
                    continue
                if op in stopped:
                    record(op, n, None, None, 0, "", stopped[op])
                    continue
                seconds, peak, runs, note, error = measure(
                    lambda: func(df), args.mem_pass_seconds)
                record(op, n, seconds, peak, runs, note if not error else "", error)
                if error and ("ModuleNotFound" in error or "ImportError" in error):
                    stopped[op] = "skipped: " + error
                elif seconds is not None and seconds > args.max_seconds:
                    stopped[op] = f"skipped: exceeded {args.max_seconds:.0f} s at a smaller size"
            del df
            gc.collect()
            if path != original:
                try:
                    os.remove(path)
                except OSError:
                    pass

    if args.online:
        print("\n=== OpenAlex API ===", flush=True)
        from orangebib import sources as bibsources
        if not bibsources.openalex_key():
            print("  No OpenAlex API key found: set the OPENALEX_API_KEY "
                  "environment variable. Requests may be refused.", flush=True)
        for n in sorted(set(args.online_sizes)):
            gc.collect()
            t0 = time.perf_counter()
            try:
                note = op_openalex_fetch(n, args.query, args.email)
                seconds, error = time.perf_counter() - t0, ""
            except Exception as exc:  # noqa: BLE001
                note, seconds, error = "", None, f"{type(exc).__name__}: {exc}"[:300]
            record("openalex_fetch", n, seconds, (process_memory_mb(), None),
                   1 if not error else 0, note, error)
            if error:
                break

    res = pd.DataFrame(rows)
    order = list(dict.fromkeys(res["operation"]))
    time_tab = res.pivot_table(index="operation", columns="records",
                               values="seconds", aggfunc="first").reindex(order)
    time_tab.to_csv(os.path.join(OUT, "summary_time.csv"))
    # Run time relative to the smallest corpus (= 100), with the corpus size
    # on the same scale as the first row for comparison.
    local = time_tab.drop(index="openalex_fetch", errors="ignore")
    local = local[[c for c in local.columns if c in sizes]]
    rel_tab = None
    if len(local.columns) and local.columns[0] == sizes[0]:
        rel_tab = local.div(local[sizes[0]], axis=0) * 100
        size_row = pd.DataFrame(
            [[100.0 * c / sizes[0] for c in rel_tab.columns]],
            index=["corpus size"], columns=rel_tab.columns)
        rel_tab = pd.concat([size_row, rel_tab])
        rel_tab.index.name = "operation"
        rel_tab.to_csv(os.path.join(OUT, "summary_time_relative.csv"))
    tables = {}
    for column, name in (("process_peak_mb", "summary_memory_process.csv"),
                         ("allocated_peak_mb", "summary_memory_allocated.csv")):
        tab = res.pivot_table(index="operation", columns="records", values=column,
                              aggfunc="first", dropna=False).reindex(order)
        tab.to_csv(os.path.join(OUT, name))
        tables[column] = tab

    pd.set_option("display.width", 200)
    print("\nRun time (seconds)\n" + time_tab.round(3).to_string(na_rep="-"))
    if rel_tab is not None:
        print(f"\nRun time relative to {sizes[0]:,} records (= 100)\n"
              + rel_tab.round(0).to_string(na_rep="-"))
    print("\nPeak memory of the process (MB)\n"
          + tables["process_peak_mb"].round(0).to_string(na_rep="-"))
    print("\nPeak memory allocated by the operation (MB)\n"
          + tables["allocated_peak_mb"].round(0).to_string(na_rep="-"))
    failed = res[res["error"].astype(str) != ""]
    if len(failed):
        print("\nNot measured:")
        for _, r in failed.iterrows():
            print(f"  {r['operation']} @ {r['records']:,}: {r['error']}")
    print(f"\nResults written to {os.path.relpath(OUT, ROOT)}{os.sep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
