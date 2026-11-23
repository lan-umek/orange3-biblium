# Bibliographic Data

> Load bibliometric data from files, combine exports from several databases,
> or query the OpenAlex API or SICRIS/COBISS.

```{figure} ../_static/img/owbibliographicdata.png
:alt: Bibliographic Data
:class: widget-screenshot

The Bibliographic Data widget.
```

## Overview

**Bibliographic Data** is the entry point of every Biblium workflow. It reads a
bibliographic corpus from one of several sources, normalises the heterogeneous
column names of different databases into a common schema (Title, Abstract,
Authors, Author Keywords, Index Keywords, Year, Cited by, DOI, …), optionally
cleans the keyword/text fields, and emits a single **Data** table that every
other Biblium widget consumes.

Because each database exports list-valued fields with its own separator
(Scopus/WoS use `; `, OpenAlex uses `|`), the widget records the source so
downstream analyses split authors, keywords and affiliations correctly.

## Inputs

- *(none)* — this is a source widget.

## Outputs

- **Data** (`Table`) — the normalised corpus, one row per document, ready for
  any downstream Biblium widget.
- **Source Overlap** (`Table`) — only when databases are combined: the number
  and share of records found in each combination of sources (for example
  *scopus; wos*).

## Loading sources

The widget offers several input modes:

- **File** — open a database export (Scopus CSV/RIS, Web of Science, OpenAlex
  CSV, PubMed, Dimensions, Lens, and 30+ formats). The format and the database
  of origin are auto-detected where possible.
- **Combine** — merge exports of the same search from two or more databases
  into one de-duplicated dataset (see *Combining databases* below).
- **OpenAlex API** — query OpenAlex directly (by keywords, author, institution,
  ISSN/journal or a DOI list), optionally restricting to open-access works, and
  choose which records are returned when the query matches more records than
  *Max Results* (see *Ordering of OpenAlex results* below).
- **SICRIS / COBISS** — load Slovenian personal/institutional bibliographies.
- **Sample datasets** — small bundled corpora for learning and testing.

## Controls

**Database** — the source database hint. Leave on *Auto-detect* for files; it
sets the correct list separator and column mapping. Set it explicitly if
auto-detection guesses wrong.

**Keyword processing** — cleaning applied to keyword (and, for the selected
categories, Title/Abstract) fields:

- **Apply stopwords** — master switch for the cleaning below.
- **General stopwords** — a bundled extended English stop-word list, always
  applied when cleaning is on.
- **Specific categories** — domain word-lists (from the bundled `stopwords.xlsx`)
  that you can toggle individually; checked categories are removed from keywords
  **and** from Title/Abstract.
- **User stopwords file** — your own one-word-per-line list to remove as well.
- **Extra stopwords** — a quick comma-separated list for ad-hoc terms.
- **Synonyms / thesaurus** — rules (`old = new`) that merge keyword variants
  into a single canonical form.

## Combining databases

The **Combine** tab takes up to six exports, each with its database of origin
(Scopus, Web of Science, OpenAlex, PubMed, Dimensions, Lens.org), and returns
one dataset in which every document appears once. The database is suggested
from the file name; check it before combining, because it selects the reader
and the list separator.

**Match records by** — how duplicates across sources are recognised:

- **DOI** — records with the same DOI (spelling and letter case are
  normalised). Records without a DOI are never matched and are all kept.
- **DOI, then title for records without DOI** — as above, and records lacking
  a DOI are matched by normalised title.
- **Title** — normalised title only.

**Keep** — which columns the combined dataset contains:

- **All columns (union)** — every column of every source. Cells are empty
  where a database does not provide the field, so analyses of
  database-specific fields cover only part of the records.
- **Only columns shared by all sources (intersection)** — no structural
  missing values, but database-specific fields are dropped.

Within a group of duplicates the values are merged: keywords and references
are united, the longest abstract and affiliation string is kept, *Cited by* is
the maximum over the sources (the per-source counts are kept as
*Cited by (scopus)*, *Cited by (wos)*, …), and other fields are taken from the
first source that provides them, in the order Scopus, Web of Science,
Dimensions, OpenAlex, Lens, PubMed. The columns **Source DB**, **N sources**,
**Merge key** and **Match type** record where each record came from and how
it was matched. The combined dataset uses the Scopus-style column names and
the `; ` separator.

The summary under the button reports the number of input records per source,
the number of unique records and the number of duplicates merged. Combining
requires `biblium` ≥ 2.19.1.

## OpenAlex API key

OpenAlex has required an API key for all requests since 13 February 2026; the
e-mail address that earlier gave access to its "polite pool" is now ignored.
The key is free: create an account at openalex.org and copy the key from
<https://openalex.org/settings/api> into the **OpenAlex API key** field. The
key is saved in the system credential store and is shared by the
Bibliographic Data, OpenAlex Enrichment and OA Finder widgets; it is not
stored in the workflow file, so a shared workflow does not carry it. When the
field is empty, the `OPENALEX_API_KEY` environment variable is used. Without
a key OpenAlex refuses the request and the widget shows how to obtain one.

## Ordering of OpenAlex results

When a query matches more records than *Max Results*, **Order by** decides
which records are downloaded:

- **Most cited first** / **Least cited first**
- **Newest first** / **Oldest first**
- **Relevance (search string)** — the default; applies to keyword queries.
  For author, institution, journal and DOI queries there is no search string,
  and the most cited records are returned instead.
- **Random sample** — a random sample of the matching records. The sample is
  seeded, so repeating the same query returns the same records; OpenAlex
  limits a sample to 10,000 records.

**Then by** adds an optional second criterion that orders records with equal
values of the first one (for example *Newest first*, then *Most cited first*).
It is not used for a random sample.

A subset selected by citations or by date is not a representative sample of
the matching literature; report the ordering together with the query.

## What it produces

A clean, column-normalised document table. Typical next steps: **OpenAlex
Enrichment** (add citations/topics/SDGs), **Filter**, and then **Main
Information** / **Bibliometric Statistics** and the analysis widgets.

## Messages

The widget reports when a required column is missing, when a file cannot be
parsed, or when an API query returns no records.

## Tips

- For multi-database studies, use the **Combine** tab when you start from
  export files. The **Deduplicate & Merge** widget removes duplicates among
  tables that are already on the canvas (for example an export and an OpenAlex
  query).
- If keyword-based widgets show merged or odd terms, check the **Database** hint
  (it controls the list separator).
