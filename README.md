# openff-stats

Stats for OpenFF software packages and publications.

## Installation

```bash
conda env create -f environment.yaml
conda activate openff-stats
```

All dependencies are declared in `pyproject.toml` and installed via `pip install -e .`.

## Overview

The pipeline has two kinds of steps:

- **Discovery** — automatically finds candidate papers, packages, or Zenodo records. Output requires **human verification** before use.
- **Collection** — reads the curated `inputs/` files and writes stats to `data/`.

```
inputs/publications.csv   ← curated list of OpenFF papers
inputs/packages.csv       ← curated list of conda-forge packages to track
inputs/zenodo.csv         ← curated list of Zenodo records with DOIs

data/citations.csv             ← citation counts from Crossref, Scholar, ChemRxiv
data/downloads.csv             ← total downloads per package (both methods)
data/downloads_yearly.csv      ← per-package per-year downloads (condastats)
data/zenodo_citations.csv      ← DataCite citation counts for Zenodo records
data/plots/openff_downloads_per_year.png
```

## Usage

### Discovery (run once, then verify manually)

```bash
# Find openff-* packages on conda-forge (writes candidates/packages.csv)
openff-stats discover-packages

# Find publications for one or more ORCID authors (writes candidates/publications.csv)
# Not all papers found will be OpenFF-related — review carefully!
openff-stats discover-publications \
    --orcid 0000-0002-1544-1476 \
    --orcid 0000-0002-4317-1381

# Find OpenFF records on Zenodo (writes candidates/zenodo.csv)
openff-stats discover-zenodo
```

After running discovery, review the `candidates/` CSV, remove non-OpenFF entries,
fill in any missing IDs (Scholar cluster ID, ChemRxiv ID), then copy to `inputs/`.

### Data collection

```bash
# Collect citation counts (Crossref + Google Scholar + ChemRxiv)
openff-stats citations

# Collect conda-forge download stats (Anaconda HTML scraping + condastats)
openff-stats downloads

# Collect DataCite citation counts for Zenodo records
openff-stats zenodo-citations

# Generate downloads-per-year bar chart
openff-stats plot-downloads

# Run everything at once (skips discovery)
openff-stats run-all
```

All commands have `--help` and accept `--input` / `--output` overrides.

## Download count methods

Two methods are used, and their counts often differ:

| Method | Column | Notes |
|--------|--------|-------|
| Anaconda HTML | `anaconda_total` | Scrapes `https://anaconda.org/conda-forge/{pkg}`. Most up-to-date total; fragile HTML parsing. |
| condastats API | `condastats_total` | Queries the Anaconda package dataset. More robust; updated periodically; historically undercounted Python 3.10+ installs (fixed in newer data). |

The `downloads_yearly.csv` file uses condastats data (the only source with monthly/yearly breakdown).

## Citation sources

| Source | Notes |
|--------|-------|
| Crossref (`crossref_citations`) | Counts DOI-to-DOI citation links within Crossref. Reliable but lower than Scholar. |
| Google Scholar (`scholar_citations`) | Scraped from Scholar cluster pages. Higher counts (includes grey literature); fragile — may fail due to CAPTCHAs. Scholar cluster IDs are in `inputs/publications.csv`. |
| ChemRxiv (`chemrxiv_views`, `chemrxiv_downloads`, `chemrxiv_citations`) | From the ChemRxiv public API. Only available for preprints. ChemRxiv record IDs are in `inputs/publications.csv`. |
| DataCite (`citation_count`) | For Zenodo records, queried via `api.datacite.org`. Tracks DOI-to-DOI citations registered with DataCite or Crossref. |

## CI

GitHub Actions runs `openff-stats run-all` on every push to `main` and commits
updated `data/` files back to the repository. Discovery steps are not run in CI
(they require human review).

## inputs/ file formats

### inputs/publications.csv
```
DOI, title, scholar_cluster_id, chemrxiv_id
```
Leave `scholar_cluster_id` or `chemrxiv_id` blank if not applicable.
Scholar cluster IDs are found in the URL parameter `cluster=NNNNN` on a Scholar page.
ChemRxiv record IDs are the hex string in ChemRxiv article URLs.

### inputs/packages.csv
```
package, category
```
`category` is either `openff` or `competitor`.

### inputs/zenodo.csv
```
zenodo_id, doi, title
```
`zenodo_id` is the numeric Zenodo record ID; `doi` is the full DOI (e.g. `10.5281/zenodo.NNNNNNN`).
