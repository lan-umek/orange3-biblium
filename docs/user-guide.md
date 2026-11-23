# User guide

Orange3-Biblium adds 81 widgets to Orange. Nobody needs all of them at once.
This guide shows how the widgets are organised, gives five small workflows to
start from, and collects practices that keep an analysis sound and repeatable.

## How the widgets are organised

The **Biblium** section of Orange's toolbox lists the widgets in the order in
which an analysis usually proceeds. They fall into nine functional groups.

| Group | Use it to | Widgets |
|:---|:---|:---|
| 1. Data input and preparation (8) | Load, enrich, clean and partition a corpus | Bibliographic Data, OpenAlex Enrichment, Semantic Scholar, Open Access Finder, Deduplicate & Merge, Filter, Setup Groups, Text Preprocessing |
| 2. Overview, counts and statistics (8) | Describe the corpus and rank its entities | Main Information, Bibliometric Counts, Bibliometric Statistics, Performance Plot, Bibliometric Laws, Production Plot, Top Cited, Reference Diversity |
| 3. Time, trends and dynamics (8) | Follow production and topics over time | Trend Analysis, Trend Topics, Top Items Timeline, Entity Over Time, Life Cycle Analysis, RaceBar, Burst Detection, Hot Topics |
| 4. Citation analysis (8) | Study how documents are cited | Citation Distribution, Citation Velocity, Citation Patterns, Disruption Index, Self-Citation Rate, Sleeping Beauty, Sleeping Beauty Plot, CiteSpace Metrics |
| 5. Text, topics and concepts (11) | Extract themes and classify content | Concept Builder, PA Concepts, Topic Modeling, Dynamic Topic Models, Thematic Map, Thematic Evolution, Conceptual Drift, Novelty Metrics, Methodology Classifier, Research Classifier, Research Gaps |
| 6. Networks (13) | Build and explore relational structure | Network Co-occurrence, Plot Bibliometric Network, Field Networks, Citation Network, Historiograph, Co-citation Network, Bibliographic Coupling, Collaboration Network, Main Path Analysis, Diachronic Network, Embedding Landscape, Entity Relationships, K-Fields Plot |
| 7. Geography, SDGs and disciplines (5) | Map countries, goals and fields | Geographic Analysis, Discipline Analysis, SDG Identifier, SDG Networks, SDG Drift |
| 8. Groups, comparison and inference (13) | Compare subgroups and test differences | Group Counts, Group Counts Plot, Group Statistics, Group Intersections, Group Associations, Crosstabs, Compare Means, Comparative Analysis, Benchmarking, Permutation Inference, Logistic Regression, Factorial Analysis, Document Clustering |
| 9. Specialised, external and output (7) | Audit, describe and report | Altmetrics Analysis, Open Science, Integrity Audit, AI Describe, Literature Matrix, Report Generator, HTML Dashboard |

A first analysis needs only groups 1 and 2. Add a group when a question calls
for it.

## Five starter workflows

Each workflow has two to four widgets and answers one question. Build one,
check that its output makes sense, and only then add the next. The workflow
in Figure 4 of the article places several such branches side by side.

**1. A first look at a corpus.**
Bibliographic Data → Main Information, and Bibliographic Data → Bibliometric
Counts. Load the bundled OpenAlex sample in Bibliographic Data. Main
Information reports the size, time span, sources and authors of the corpus;
Bibliometric Counts ranks the entity you choose (sources, authors, keywords,
countries).

**2. Performance indicators.**
Bibliographic Data → Bibliometric Statistics → Performance Plot. Bibliometric
Statistics computes the h-index and related indicators per source, author or
country; Performance Plot displays them.

**3. A keyword map.**
Bibliographic Data → Network Co-occurrence → Plot Bibliometric Network. Start
with author keywords and about 50 nodes; raise the minimum number of
occurrences if the map is crowded.

**4. Comparing groups.**
Bibliographic Data → Setup Groups → Group Associations. Define two or three
groups (for example publication periods) in Setup Groups. Group Associations
shows which journals, keywords or authors are over- or under-represented in
each group, with tests.

**5. Thematic trends.**
Bibliographic Data → Trend Topics, and Bibliographic Data → Thematic Map.
Trend Topics orders keywords by when they were most used; Thematic Map places
themes by centrality and density.

Any Orange widget can be attached to these chains. A Data Table after any
Biblium widget shows exactly what it produced.

## Good practices

### Preparing data

- **Check the database.** When loading a file, confirm the *Database* setting.
  It selects the reader and the separator of list-valued fields; a wrong
  setting shows up as merged authors or keywords.
- **Combine before you analyse.** When a study uses several databases, use the
  *Combine* tab of Bibliographic Data, and report the matching rule (DOI,
  DOI then title, or title) and the number of duplicates merged. Matching by
  DOI alone never matches records without a DOI.
- **Know which fields survive.** *Union* keeps every column but leaves cells
  empty where a database lacks the field, so analyses of such fields cover
  only part of the corpus. *Intersection* avoids this at the price of fewer
  fields. Check a field's coverage before interpreting it.
- **Report how a subset was chosen.** When an OpenAlex query matches more
  records than you download, the *Order by* setting decides which ones you
  get. The most cited or the newest records are not a representative sample;
  use *Random sample* when representativeness matters.
- **Get an OpenAlex API key.** OpenAlex requires a free key for all requests.
  Enter it once in the *OpenAlex API key* field; it is stored in the system
  credential store, not in the workflow file.
- **Look at the data.** Put a Data Table after Bibliographic Data and read a
  few rows before going further.

### Interpreting statistics

- **Heed the warnings.** When a widget warns that many cells have a low
  expected frequency, do not read the chi-square result literally: use the
  permutation p-values, or analyse fewer, more frequent entities.
- **Use the corrected p-values.** A single run tests many entities or cells.
  Report the Benjamini–Hochberg or Bonferroni corrected values, not the raw
  ones.
- **Read the inertia.** A correspondence-analysis biplot is trustworthy only
  as far as its two dimensions explain the table. When the widget reports low
  cumulative inertia, confirm any pattern against the numerical tables.
- **Separate strength from significance.** With large corpora small
  differences become significant. Look at Cramér's V and at the residuals,
  not only at p-values.
- **Do not treat groups as given.** Results depend on how groups are defined
  in Setup Groups. State the definition, and check that conclusions hold
  under a reasonable alternative.

### Working with large corpora

- Run time grows roughly in proportion to the number of records. On a desktop
  computer 50,000 records take a few seconds for most operations and well
  under a minute for dynamic topic modelling, within 1 GB of memory (see the benchmark in
  `examples/benchmark/`).
- Keep the number of entities moderate (top 50 to 100). Larger tables are
  slower, sparser and harder to read.
- Filter early. A Filter widget directly after loading shortens every step
  that follows.
- Topic models and permutation tests are the slowest steps. Tune their
  settings on a sample before running them on the full corpus.

### Keeping an analysis reproducible

- Save the workflow file (`.ows`): it stores every widget setting.
- Record the versions of Orange, Orange3-Biblium and Biblium, and the date of
  any query to an external service; such results change as the service is
  updated.
- Export the tables behind every figure you publish.
- For a published study, install fixed versions, for example
  `pip install Orange3-Biblium==0.4.0`.

### When something stops working

- **A warning about the Biblium version.** Upgrade with
  `pip install -U Orange3-Biblium` using Orange's Python, then restart Orange.
- **An OpenAlex request is refused.** Check the API key; the free plan also
  has a daily limit.
- **A widget fails after an update.** Reinstall the previous version, for
  example `pip install Orange3-Biblium==0.3.0 biblium==2.16.1`, and report
  the problem at <https://github.com/lan-umek/orange3-biblium/issues>.
- **A widget shows an error.** Read the message in the widget; it states what
  is missing (a column, a package, a network connection).
