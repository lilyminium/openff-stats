# openff-stats

Stats for OpenFF software packages and publications.

**Note: I've only manually checked the Google Scholar numbers for citations.**

Note that Google Scholar citations require selenium.
I've essentially hardcoded this to work on my machine (tm);
no guarantees it'll work for you.

Date last updated: 2026-03-04

## How to update

There's more detail in the rest of this README, but quickly, to update publications:

1. Add new papers (one DOI at a time):

    ```bash
    openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558"
    ```

2. Open `inputs/publications.csv` and quickly verify the new row(s):
    - remove anything not OpenFF-related
        - optionally fill `scholar_cluster_id` (for Scholar citation counts)
            - `scholar_cluster_id` is Google Scholar's internal ID for a paper record group (all versions/hosts of the same paper share this cluster)
            - manual lookup: open https://scholar.google.com, search the paper title, click **Cited by** on the matching result, then copy the number from `cluster=...` (or `cites=...`) in the URL
            - example: if the URL contains `cluster=10951048273842882493`, set `scholar_cluster_id` to `10951048273842882493`
    - optionally fill `chemrxiv_id` (for ChemRxiv metrics)

3. If needed, refresh Scholar cluster IDs automatically:

    ```bash
    openff-stats scholar-clusters
    ```

Then run `openff-stats run-all` to get citations.

## Please read these caveats before using these numbers

### Download counts

Please take these download counts with a gigantic pile of salt.
They are *not* a reflection of user numbers.
These numbers vastly overcount "real" installs of our packages for the following reasons:

- many openff packages depend on each other and downloading one will pull in others. As the "total OpenFF conda-forge downloads" simply sums all downloads across all packages, this means the figure is likely inflated at least 5-fold, likely closer to 10.
- many, perhaps most, of these downloads will simply be from running CI and tests.

Methodology note: where there are two versions of a package, e.g. openff-toolkit and openff-toolkit-base, I have only used the download counts of the second. So these at least are not double counted.

### Citations

Here we use Google Scholar and CrossRef numbers because they're easy. Out of Google Scholar, CrossRef, and Scopus, Google Scholar tends to have the highest citation numbers. One thing to note, we have anecdotally seen Google Scholar numbers fluctuate depending on when we look at them, possibly as a result of behind-the-scenes algorithm updates. The date is above.

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
data/github_repos.csv          ← GitHub repos that import or depend on openff.toolkit
data/plots/openff_downloads_per_year.png
```

## Usage

### Discovery (run once, then verify manually)

I also suggest updating manually. My original procedure is below.

**The document to update is inputs/publications.csv**

You can just update the CSV yourself, or more conveniently, add a publication via DOI.

```
openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558"
```


**Original procedure**


I started off with this automated list but it took 10+ min to download all publications, and 20 min to sort through all the OpenFF ones. I've suggested a base list of authors to check publications for. Note some people are not on the list due to possible confusion with other projects, e.g. OpenFE, and some just publish a lot!

```bash
# Find openff-* packages on conda-forge (writes candidates/packages.csv)
openff-stats discover-packages

# Find publications for one or more ORCID authors (writes candidates/publications.csv)
# Not all papers found will be OpenFF-related — review carefully!
openff-stats discover-publications \
    --orcid-csv inputs/orcids.csv

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

# Search GitHub for repos that import or depend on openff.toolkit
# Requires GH_API_TOKEN env var (a GitHub personal access token)
openff-stats github-repos

# Generate downloads-per-year bar chart
openff-stats plot-downloads

# Run everything at once (skips discovery; skips GitHub if GH_API_TOKEN not set)
openff-stats run-all
```

All commands have `--help` and accept `--input` / `--output` overrides.

## Download count methods

Two methods are used, and their counts often differ:

| Method | Column | Notes |
|--------|--------|-------|
| Anaconda API | `anaconda_total` | Queries `https://api.anaconda.org/package/conda-forge/{pkg}`. Most up-to-date total. |
| condastats API | `condastats_total` | Queries the Anaconda package dataset. More robust; updated periodically, so may undercount between updates. |

The `downloads_yearly.csv` file uses condastats data (the only source with monthly/yearly breakdown).

## Citation sources

| Source | Notes |
|--------|-------|
| Crossref (`crossref_citations`) | Counts DOI-to-DOI citation links within Crossref. Reliable but lower than Scholar. |
| Google Scholar (`scholar_citations`) | Scraped from Scholar cluster pages. Higher counts (includes grey literature); fragile — may fail due to CAPTCHAs. Scholar cluster IDs are in `inputs/publications.csv`. |
| ChemRxiv (`chemrxiv_views`, `chemrxiv_downloads`, `chemrxiv_citations`) | From the ChemRxiv public API. Only available for preprints. ChemRxiv record IDs are in `inputs/publications.csv`. |
| DataCite (`citation_count`) | For Zenodo records, queried via `api.datacite.org`. Tracks DOI-to-DOI citations registered with DataCite or Crossref. |

## GitHub code search

`openff-stats github-repos` searches GitHub's code search API for public repositories
that import or declare a dependency on `openff.toolkit`, and writes `data/github_repos.csv`.

Requires a GitHub personal access token in the `GH_API_TOKEN` environment variable.
No special scopes are needed — public code search works with any valid token.

### What is searched

Nine queries cover the main ways the toolkit appears in a repository:

| Query | `how` label in CSV |
|-------|--------------------|
| `import openff.toolkit` in Python files | `import openff.toolkit (Python)` |
| `from openff.toolkit import ...` in Python files | `from openff.toolkit import ... (Python)` |
| `import openff.toolkit` in Jupyter notebooks | `import openff.toolkit (Jupyter notebook)` |
| `from openff.toolkit import ...` in Jupyter notebooks | `from openff.toolkit import ... (Jupyter notebook)` |
| `openff-toolkit` in `pyproject.toml` | `openff-toolkit in pyproject.toml` |
| `openff-toolkit` in `requirements.txt` | `openff-toolkit in requirements.txt` |
| `openff-toolkit` in `environment.yml` | `openff-toolkit in environment.yml` |
| `openff-toolkit` in `setup.cfg` | `openff-toolkit in setup.cfg` |
| `openff-toolkit` in `setup.py` | `openff-toolkit in setup.py` |

Queries are run in the order above.
When a repository matches more than one query, only the **first** (highest-priority) match is kept,
so direct runtime imports take precedence over dependency-file declarations.

### Output columns

| Column | Description |
|--------|-------------|
| `repo` | Repository full name (`owner/repo`) |
| `url` | URL to the repository on GitHub |
| `how` | How the toolkit was found (see table above) |
| `evidence_url` | Permalink to the specific file that matched (blob SHA URL) |

### Working around the 1 000-result cap

GitHub's code search API returns at most 1 000 results per query.
When a query hits this cap the pipeline automatically re-runs it split across
six file-size buckets (`0..500`, `501..2000`, …, `>150000` bytes), unions the results,
and recurses up to two levels if any bucket still overflows.
This gives a best-effort complete count even for popular queries.

### Caveats

- Counts only **public** repositories — private usage is not captured.
- Forks are included; the numbers therefore overcount unique projects.
- GitHub's `total_count` for a query is an estimate and can differ from the
  number of unique repos actually retrieved after pagination.

## CI

GitHub Actions runs `openff-stats run-all` on manual trigger (`workflow_dispatch`) and commits
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
