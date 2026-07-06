# openff-stats

Stats for OpenFF software packages and publications.

**Note: I've only manually checked the Google Scholar numbers for citations.**
Google Scholar citations require Selenium + Firefox; this is essentially
hardcoded to work on my machine (tm), no guarantees it'll work for you.
Expect to solve the occasional CAPTCHA by hand in the Firefox window it
opens (see the methodology section).

Date last updated: 2026-07-05

## Contents

- [Contents](#contents)
- [How it works](#how-it-works)
- [Tutorial: add a publication and check its citations](#tutorial-add-a-publication-and-check-its-citations)
- [How to add a new source](#how-to-add-a-new-source)
  - [Examples: querying DOIs](#examples-querying-dois)
  - [Google Scholar lookup by DOI](#google-scholar-lookup-by-doi)
  - [Verifying a DOI or a match by its link](#verifying-a-doi-or-a-match-by-its-link)
- [inputs/ file formats](#inputs-file-formats)
- [Data collection](#data-collection)
- [Optional bulk discovery](#optional-bulk-discovery)
- [Methodology and caveats — read before using these numbers](#methodology-and-caveats--read-before-using-these-numbers)
  - [Publication citations (`data/citations.csv`)](#publication-citations-datacitationscsv)
  - [Zenodo citations (`data/zenodo_citations.csv`)](#zenodo-citations-datazenodo_citationscsv)
  - [Conda-forge download counts (`data/downloads.csv`, `data/downloads_yearly.csv`)](#conda-forge-download-counts-datadownloadscsv-datadownloads_yearlycsv)
  - [GitHub repo imports and stars (`data/github_repo_stars.csv`)](#github-repo-imports-and-stars-datagithub_repo_starscsv)
- [Installation](#installation)
- [CI](#ci)

## How it works

Every source is a **manually curated** CSV in `inputs/`. Each source kind is
a directory of CSVs where the **filename is the group classification** —
e.g. `inputs/publications/force-field.csv` holds the force-field papers.
Collection commands read every CSV in the directory, tag rows with their
group, and print cumulative sums per group. Nothing is scraped into the
pipeline automatically — you decide what goes in `inputs/`.

```
inputs/publications/<group>.csv   ← papers (DOIs) to track citations for
                                    (force-field.csv, general.csv, …)
inputs/packages/<group>.csv       ← conda-forge packages to track downloads for
                                    (openff.csv, competitor.csv)
inputs/zenodo/<group>.csv         ← Zenodo records to track DataCite citations for
                                    (general.csv, qcsubmit.csv, yammbs.csv, …)
inputs/github_repos/<group>.csv   ← GitHub repos, grouped by the package they
                                    import (openff-toolkit.csv, …)

data/citations.csv             ← Crossref / OpenAlex / Semantic Scholar /
                                    Google Scholar / ChemRxiv counts, with group
data/downloads.csv             ← total downloads per package, with group
data/downloads_yearly.csv      ← per-package per-year downloads, with group
data/zenodo_citations.csv      ← DataCite citations, long form (one row per
                                    record-year; citation_count = record total)
data/github_repo_stars.csv     ← star counts for the curated repos, with group
```

## Tutorial: add a publication and check its citations

Walkthrough of the full flow for a new paper, from DOI to citation counts.

1. **Add the paper.** Fetches Crossref metadata (title, authors, year),
   verifies the DOI resolves, de-dupes against every group file, and appends
   to `inputs/publications/<group>.csv` (default group: `general`; pass
   `--group force-field` for a force-field paper):

   ```bash
   openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558" --group force-field
   ```

2. **Check the row in `inputs/publications/<group>.csv`.** Confirm the
   metadata looks right. `scholar_cluster_id` and `chemrxiv_id` are still
   blank at this point — that's expected.

3. **Get the Google Scholar cluster ID.** Either pass `--scholar` in step 1
   to fetch it automatically (best-effort — the paper is still added if
   Scholar fails to match), or fetch it separately and save it:

   ```bash
   openff-stats scholar-lookup "10.1021/acs.jpcb.4c01558" --save
   ```

   This searches Scholar by DOI, falls back to the title, and only saves a
   confident match. If nothing matches confidently, it prints candidate
   links instead — see [Google Scholar lookup by DOI](#google-scholar-lookup-by-doi)
   below for picking one by hand.

4. **Run the citation check.** Collects Crossref, OpenAlex, Semantic
   Scholar, Google Scholar (via the cluster ID), and ChemRxiv citation
   counts for every row of every group file in
   `inputs/publications/`, writes `data/citations.csv` (with a `group`
   column), and prints cumulative sums per group and overall:

   ```bash
   openff-stats citations
   ```

   (`openff-stats run-all` runs this plus every other collector in one go.)

## How to add a new source

One command per source type. Each fetches metadata, de-duplicates, and appends
a row to the curated CSV — so adding a source is a one-liner, and you can always
hand-edit the CSV afterwards.

All `add-*` commands take `--group NAME` to choose the target file
(`inputs/<kind>/<NAME>.csv`); the duplicate check always spans every group,
so a source can only live in one group.

```bash
# Any DOI(s) — Zenodo DOIs are auto-detected by their 10.5281/zenodo. prefix
# and routed to inputs/zenodo/<group>.csv; everything else is a publication.
openff-stats add-doi "10.1021/acs.jcim.2c01153" "10.5281/zenodo.5503442"

# A paper (Crossref metadata). Add --scholar to also fill the Scholar cluster ID.
openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558" --group force-field

# A GitHub repo (OWNER/REPO or a github.com URL); group = the package it imports.
openff-stats add-github-repo openforcefield/openff-toolkit

# A Zenodo record (numeric ID, DOI, or record URL).
openff-stats add-zenodo 10.5281/zenodo.18842670 --group qcsubmit

# A conda-forge package: edit inputs/packages/<group>.csv directly (one
# `package` column; the filename is the group, e.g. openff.csv).
```

Then run `openff-stats run-all` to refresh the stats.

### Examples: querying DOIs

Query a single DOI without adding anything:

```bash
# What does this DOI point to? (registered title + publisher, via doi.org)
openff-stats verify-doi "10.1021/acs.jcim.2c01153"

# What are its Google Scholar citations? (prints the match and Cited-by count)
openff-stats scholar-lookup "10.1021/acs.jcim.2c01153"
```

Add a single DOI — `add-doi` works for both papers and Zenodo records:

```bash
openff-stats add-doi "10.1021/acs.jcim.2c01153"     # → inputs/publications/general.csv
openff-stats add-doi "10.5281/zenodo.5503442"       # → inputs/zenodo/general.csv (Zenodo prefix)
```

Add a whole list from a text file into its own group (one DOI per line;
blank lines and `#` comments are skipped; mixed papers + Zenodo records is
fine — each lands in the right directory under the same group name). For
example, DOIs extracted from the qcsubmit and yammbs repos:

```bash
openff-stats add-doi --file ~/Downloads/qcsubmit_extracted_dois.txt --group qcsubmit
openff-stats add-doi --file ~/Downloads/yammbs_extracted_dois.txt --group yammbs
```

Each DOI is reported as it's processed (`added` / `already present` /
`FAILED`); failures don't stop the batch, and already-present DOIs are
skipped, so re-running the same file is safe.

Then collect citation counts for everything curated — each command prints
cumulative sums per group as well as the overall total:

```bash
openff-stats citations          # papers   → data/citations.csv
openff-stats zenodo-citations   # Zenodo   → data/zenodo_citations.csv
```

### Google Scholar lookup by DOI

Scholar citation counts need a `scholar_cluster_id` per paper (Scholar's
internal ID for the group of all versions of a paper). Look one up by DOI:

```bash
# One DOI — print the matched paper, its cluster ID, and Cited-by count:
openff-stats scholar-lookup "10.1021/acs.jpcb.4c01558"

# ...and write the cluster ID into whichever inputs/publications/*.csv holds the DOI:
openff-stats scholar-lookup "10.1021/acs.jpcb.4c01558" --save

# Every DOI at once — fill scholar_cluster_id for all rows still missing one:
openff-stats scholar-clusters                     # add --overwrite-existing to redo all
```

Both search Scholar for the DOI, fall back to the paper's title, and
**validate every candidate against that title** — only a confident match is
saved, so you won't silently store the wrong cluster. `scholar-lookup` prints
the candidates when nothing matches confidently so you can pick one by hand
(paste the ID into the `scholar_cluster_id` column); `scholar-clusters` leaves
those rows blank and reports the count.

### Verifying a DOI or a match by its link

`scholar-lookup` prints a clickable `https://doi.org/…` link and a
`https://scholar.google.com/scholar?cluster=…` link for each candidate, so you
can open them and eyeball the match. Add `--open` to launch the DOI page and
the best-match Scholar page in your browser automatically.

To just check that a DOI resolves and see what it points to (its registered
title and publisher, via doi.org — no scraping):

```bash
openff-stats verify-doi "10.1021/acs.jpcb.4c01558"
```

`add-publication-doi` runs this resolution check automatically before adding a
paper, so a typo'd or dead DOI is rejected rather than stored (skip with
`--no-verify`).

Manual alternative: search the title on <https://scholar.google.com>, click
**Cited by** on the right result, and copy the number after `cluster=` (or
`cites=`) in the URL.

## inputs/ file formats

Each kind is a directory; the CSV filename is the group classification.

| Directory | Columns per CSV |
|-----------|-----------------|
| `publications/` | `DOI, title, authors, year, scholar_cluster_id, chemrxiv_id` |
| `packages/` | `package` |
| `zenodo/` | `zenodo_id, doi, title, creators, publication_year, resource_type` |
| `github_repos/` | `repo, url, status, notes` (group = the package the repos import) |

`scholar_cluster_id` / `chemrxiv_id` may be blank. In `github_repos/`,
`status` is `manual` (you added it), `auto` (seeded from discovery), or
`exclude` (kept for the record but skipped by collection). Group names are
load-bearing: e.g. papers in `publications/force-field.csv` are what the
force-field citation subtotal counts.

## Data collection

```bash
openff-stats citations          # Crossref + OpenAlex + Semantic Scholar + Google Scholar + ChemRxiv
openff-stats downloads          # conda-forge downloads (Anaconda + condastats), sums per group
openff-stats zenodo-citations   # DataCite citations for Zenodo records, sums per group
openff-stats github-stars       # star counts + repo-import counts per group (needs GITHUB_TOKEN)
openff-stats github-descriptions # descriptions + auto topic category (needs GITHUB_TOKEN)

openff-stats run-all            # everything above except github-descriptions
```

All commands take `--help` and accept `--input` / `--output` overrides.
Conda-forge download sums and GitHub repo-import sums are reported
separately, each broken down by group.

## Optional bulk discovery

These help you *find* candidate sources; they write to `candidates/` (which is
gitignored) and never feed collection directly. Review the output, then add
approved rows to `inputs/` (or use the `add-*` commands above).

```bash
openff-stats discover-publications --orcid-csv inputs/orcids.csv
openff-stats discover-packages
openff-stats discover-dependents          # conda-forge reverse deps of openff-toolkit
openff-stats discover-zenodo
openff-stats discover-github-repos        # GitHub code search (needs GITHUB_TOKEN)
```

`discover-github-repos` takes `--package` (conda-forge name) and
`--import-name` (Python import path) so you can sweep any package; it flags
repos not already in any `inputs/github_repos/*.csv` group (sorted first) so
review is a quick scan of the top rows.

## Methodology and caveats — read before using these numbers

How each number is measured, and why none of them should be quoted without
the caveats. Every count is re-fetched from scratch on each collection run.

### Publication citations (`data/citations.csv`)

One row per curated paper in `inputs/publications/`, with one column per
source. A blank cell means the lookup failed or the paper has no ID for that
source — blank is "unknown", never 0.

| Column | How it's measured |
|--------|-------------------|
| `crossref_citations` | The `is-referenced-by-count` field from the Crossref REST API (`api.crossref.org/works/<DOI>`): the number of DOI-to-DOI citation links deposited with Crossref. Reliable but a lower bound — citing works whose publishers don't deposit reference lists are missed. |
| `openalex_citations` | The `cited_by_count` field from the OpenAlex API (`api.openalex.org/works/<DOI>`). OpenAlex aggregates Crossref plus other indexes, so it typically sits between Crossref and Google Scholar. Free, no key, full coverage — the most robust "higher than Crossref" number. |
| `semantic_scholar_citations` | The `citationCount` field from the Semantic Scholar Graph API (`api.semanticscholar.org/graph/v1/paper/DOI:<DOI>`). Coverage of the chemistry literature is patchy: some of our papers are missing from the corpus entirely (a note is printed) and some counts run well below the other sources — treat as a cross-check, not a headline number. |
| `scholar_citations` | The "Cited by N" count scraped from the paper's Google Scholar cluster page (`scholar.google.com/scholar?cluster=<scholar_cluster_id>`) with Selenium + Firefox. Cluster IDs are matched by DOI/title search and validated against the Crossref title before being stored (see [Google Scholar lookup by DOI](#google-scholar-lookup-by-doi)); collection only ever *reads* the stored IDs. Scholar counts are the highest of Scholar/Crossref/Scopus (they include preprints, theses, etc.) and fluctuate over time; scraping is fragile, and any failure leaves the cell blank. Requests are paced ~10 s apart, a blank result is retried up to 5 times with a 15 s cooldown before each retry, and a warning is printed for any paper still blank after all retries. |
| `chemrxiv_views`, `chemrxiv_downloads`, `chemrxiv_citations` | The "Abstract Views", "Content Downloads", and "Citations" metrics from the ChemRxiv public API (`/items/<chemrxiv_id>`). Preprints only; the citation number is ChemRxiv's own and counts citations of the preprint, not the published paper. |

The three broad-coverage sources measure different things. **Google
Scholar** casts the widest net — it counts citations from preprints,
theses, books, and other grey literature — so its numbers run the highest,
but they come from scraping (fragile, CAPTCHAs, fluctuates over time) and
each paper needs a curated cluster ID. **OpenAlex** aggregates Crossref
with other scholarly indexes behind a free, keyless API with full coverage
of this corpus; its counts typically land between Crossref and Scholar,
making it the best reliability-per-effort number. **Semantic Scholar** is
strongest in computer science and biomedicine; on this chemistry-leaning
corpus its coverage is the weakest (several papers missing, some counts far
below every other source), so treat it as a cross-check only. Empirically
the totals order as Scholar > OpenAlex > Crossref > Semantic Scholar.

Google Scholar is the only manually spot-checked number. The "force-field
papers" subtotal is simply the sum over rows whose group file is
`force-field.csv`.

All Scholar traffic (collection and the lookup commands alike) is throttled
at the driver level to at most 2 requests per second, on top of the pacing
above.

**Scraping many papers (or re-running repeatedly) will trip Google's bot
detection.** Two things can happen: Scholar may serve result pages with the
"Cited by" link silently stripped (the count is left blank and a warning is
printed), or it may show a CAPTCHA. **You may need to fill in CAPTCHAs
manually to get a complete run**: the Firefox window Selenium drives is
visible, so solve one whenever it appears — with the retry cooldowns the
run then picks back up on its own. If blanks persist,
wait a few hours (or a day) and re-run `openff-stats citations`; the stored
cluster IDs are untouched by collection, so a re-run only re-checks the
counts.

### Zenodo citations (`data/zenodo_citations.csv`)

Zenodo mints its DOIs (`10.5281/zenodo.*`) through **DataCite** (the DOI
registration agency for data/software, Crossref's counterpart), so citation
counts come from the DataCite API (`api.datacite.org/dois/<doi>`). The file
is long form: one row per record-year from DataCite's `citationsOverTime`
breakdown, and `citation_count` is the **sum of those per-year counts** —
DataCite's own `citationCount` attribute lags its per-year data and is not
used. Records with no citations keep a single row with a blank `year`.

Caveats:

- DataCite only knows about formal DOI-to-DOI citation links, so these
  counts are conservative — most dataset reuse is never cited this way.
- A record *hosted* on Zenodo but registered under an external DOI (e.g.
  conference proceedings with a `10.25080/...` DOI) is not in DataCite and
  would always report 0; track those in `inputs/publications/` (Crossref)
  instead.

### Conda-forge download counts (`data/downloads.csv`, `data/downloads_yearly.csv`)

Two independent measurements per curated package:

- `anaconda_total` — the `ndownloads` field from the Anaconda.org API
  (`api.anaconda.org/package/conda-forge/<pkg>`): lifetime total across all
  versions and platforms. The most current number.
- `condastats_total` — the sum of monthly counts from
  [condastats](https://github.com/sophiamyang/condastats) (backed by the
  public `anaconda-package-data` dataset). Also the source of the per-year
  breakdown in `data/downloads_yearly.csv`. Updated roughly monthly, so it
  trails the Anaconda API total.

Please take these download counts with a gigantic pile of salt. They are *not*
a reflection of user numbers, and vastly overcount "real" installs:

- Many OpenFF packages depend on each other, so downloading one pulls in
  others. The "total OpenFF conda-forge downloads" simply sums all downloads
  across all packages, so it is likely inflated at least 5-fold, probably ~10.
- Many, perhaps most, downloads are just CI and tests.
- Where a package has a metapackage + `-base` pair (e.g. `openff-toolkit`
  and `openff-toolkit-base`), only the `-base` variant is in the curated
  list, so at least those are not double counted.

### GitHub repo imports and stars (`data/github_repo_stars.csv`)

"Repo imports" for a package = the number of curated repos in
`inputs/github_repos/<package>.csv` (rows with `status == exclude` are
skipped). Candidates are found by GitHub code search — runtime imports
(`import`/`from <import name>` in `.py` and `.ipynb` files) plus declared
dependencies (the conda-forge name in `setup.py`, `setup.cfg`,
`pyproject.toml`, `requirements.txt`, `environment.yml`, `pixi.toml`) — and
then human-reviewed before entering the curated list (`status` records
whether a row was added manually or seeded from discovery).

`stars` is `stargazers_count` from one GitHub Repos API call per repo;
repos that have gone private, been deleted, or renamed are recorded with 0
stars.

Caveats: code search only sees public repositories that GitHub has indexed,
and only what the search queries match — private/unindexed usage is
invisible, so the import counts are a lower bound and only as good as the
curation.

## Installation

Preferred (pixi):

```bash
pixi install
pixi run openff-stats --help
```

Alternative (conda, also used by CI):

```bash
conda env create -f environment.yaml
conda activate openff-stats
```

All dependencies are declared in `pyproject.toml` and installed via
`pip install -e .`. Google Scholar scraping additionally requires Firefox and
geckodriver.

## CI

GitHub Actions runs `openff-stats run-all` on manual trigger
(`workflow_dispatch`) and commits updated `data/` files and the README date
stamp back to `main`. Discovery and `github-descriptions` are not run in CI
(they need human review).
