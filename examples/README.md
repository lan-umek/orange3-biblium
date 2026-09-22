# Reproducibility package — SoftwareX figures

Everything needed to reproduce the illustrative examples of

> L. Umek, *Biblium for Orange: A visual programming add-on for bibliometric
> and scientometric analysis*, SoftwareX (submitted).

No external data are required: all examples use the **OpenAlex sample dataset
of 613 highly cited scientometrics publications** that is distributed with the
Biblium library and installed automatically with this add-on.

## Contents

| File | Purpose |
|---|---|
| `SoftwareX_figures.ows` | The Orange workflow shown in Figure 4, with the widget settings used for Figures 1–4 |
| `reproduce_figures.py` | Headless reproduction and verification of every numerical table behind Figures 2 and 3 |
| `expected/*.csv` | Reference outputs generated with the archived release |

## Option A — reproduce in the graphical interface

1. Install the exact archived version:

   ```bash
   pip install Orange3-Biblium==0.3.0
   ```

   or, inside Orange, *Options ▸ Add-ons ▸ Orange3-Biblium*.

2. Start Orange and open `SoftwareX_figures.ows`
   (*File ▸ Open*, or drag the file onto the canvas).

3. Open the **Bibliographic Data** widget and click **Load** — the OpenAlex
   sample is preselected. Then run the workflow.

Each widget already carries the parameters reported in the paper, so the
displayed tables and plots correspond to Figures 2–4 directly.

## Option B — reproduce without a graphical session

```bash
python examples/reproduce_figures.py
```

The script loads the same dataset, applies the same parameters, calls the same
computational methods the widgets use, and compares every resulting table with
the stored references in `expected/`, cell by cell (absolute tolerance 1e-6).
It exits with status 0 only when all tables match, so it doubles as a
reproducibility check in continuous integration.

To regenerate the references after an intentional change:

```bash
python examples/reproduce_figures.py --generate
```

## Parameters used in the manuscript

**Figure 2 — Group Associations.** Entity type *Sources (Journals)*; three
non-overlapping publication periods obtained with *Setup Groups* by splitting
the publication year at 2008 and 2014 (`–2008`, `2009–2014`, `2015–`); top 10
entities; minimum frequency 5; all six statistics enabled; balloon plot
restricted to cells with |standardized residual| ≥ 1.0.

**Figure 3 — Entity Relationships.** Row entity *Authors*, column entity
*Author Keywords*, top 20 × top 20, minimum frequency 3; chi-square test,
correspondence analysis and association measures enabled; CA biplot shown.

**Figure 4 — Workflow.** The canvas in `SoftwareX_figures.ows`. The OpenAlex
Enrichment widget queries the OpenAlex API; because the API evolves, the
enrichment branch may return slightly different citation counts over time.
The tables verified by `reproduce_figures.py` are computed from the sample
file alone and are therefore stable.

## Environment

The reference outputs were produced with the versions recorded in
`expected/environment.txt`. Results are deterministic across platforms except
for the permutation p-values in the Group Associations widget, which use a
fixed seed (42) and are therefore also reproducible.
