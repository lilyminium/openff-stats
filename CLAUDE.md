# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
conda env create -f environment.yaml
conda activate openff-stats
# environment.yaml installs the package in editable mode via pip install -e .
```

Google Scholar scraping requires Firefox and geckodriver (hardcoded for macOS).

## Common commands

```bash
# Add a source (each fetches metadata, dedupes, appends to the curated CSV)
openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558"   # optionally --scholar
openff-stats add-github-repo openforcefield/openff-toolkit
openff-stats add-zenodo 10.5281/zenodo.18842670

# Google Scholar lookup by DOI (find/store scholar_cluster_id)
openff-stats scholar-lookup "10.1021/acs.jpcb.4c01558" --save

# Collect all stats (citations, downloads, zenodo, github stars, plot)
openff-stats run-all

# Individual collection steps
openff-stats citations
openff-stats downloads
openff-stats zenodo-citations
openff-stats github-stars                 # requires GITHUB_TOKEN
openff-stats plot-downloads

# GitHub bubble chart (manual: needs reviewed category column)
openff-stats github-descriptions          # then review category, then:
openff-stats plot-github-bubbles

# Optional bulk discovery → candidates/ (gitignored, human-reviewed)
openff-stats discover-publications --orcid-csv inputs/orcids.csv
openff-stats discover-packages
openff-stats discover-dependents          # conda-forge reverse deps of openff-toolkit
openff-stats discover-zenodo
openff-stats discover-github-repos        # GitHub code search; requires GITHUB_TOKEN
openff-stats scholar-clusters             # bulk-fill scholar_cluster_id by title
```

All commands accept `--help` and most accept `--input`/`--output` path overrides.

## Architecture

Every source is a **manually curated** CSV in `inputs/`. Collection reads those
files and writes stats to `data/`. Discovery is optional and only ever writes
`candidates/` for human review — it never feeds collection directly.

**Curation** (manual)
- `add-*` commands append one row to an `inputs/*.csv` (metadata fetched, deduped)
- `discover-*` commands write `candidates/*.csv` (gitignored) for review

**Collection** (automated, run by CI)
- Reads `inputs/*.csv` → writes `data/*.csv` and `data/plots/`

### Source modules (`src/openff_stats/`)

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Click entry point; all commands defined here with lazy imports |
| `publications.py` | `add-publication-doi`, `scholar-lookup`; ORCID/Crossref discovery; Scholar (Selenium) / Crossref / ChemRxiv citation collection |
| `downloads.py` | conda-forge package + dependent-tree discovery; Anaconda API + condastats download collection |
| `zenodo.py` | `add-zenodo`; Zenodo discovery; DataCite citation collection |
| `github.py` | `add-github-repo`; curated-list loader; star/description collection; code-search discovery (requires `GITHUB_TOKEN`) |
| `plotting.py` | Downloads bar chart, dependents/dep-tree charts, GitHub bubble chart |

### Key data flows

- `inputs/publications.csv` → `publications.py` → `data/citations.csv`
  - Scholar scraping uses a shared headless Firefox driver (`_scholar_driver` global in `publications.py`); lazy-initialized, closed after collection
  - `scholar_cluster_id` (Google Scholar's internal ID) is needed for Scholar citation counts. Find it by DOI with `scholar-lookup` (searches Scholar, validates the hit against the Crossref title before saving — parses the cluster ID from each result link's `data-clk` `d=<id>` field), or bulk-fill by title with `scholar-clusters`
  - `force_field_paper` column controls per-subset summary stats printed at the end of `citations`

- `inputs/packages.csv` → `downloads.py` → `data/downloads.csv` + `data/downloads_yearly.csv`
  - Two parallel methods: Anaconda API (most current totals) and condastats (has monthly/yearly breakdown)
  - `category` column is `openff` or `competitor`; only `openff` packages are summed in totals

- `inputs/github_repos.csv` → `github.py` → `data/github_repo_stars.csv` (+ descriptions, bubble plot)
  - `load_curated_repos()` drops rows with `status == exclude`; used by all github collectors and the bubble plot
  - `status` is `manual` / `auto` / `exclude`

- `inputs/zenodo.csv` → `zenodo.py` → `data/zenodo_citations.csv`

### CI

GitHub Actions (`.github/workflows/gh-ci.yaml`) is triggered manually (`workflow_dispatch`) and runs `openff-stats run-all`, then commits updated `data/` and `README.md` (date stamp) back to `main`. `run-all` collects GitHub *stars* for the curated repo list (one cheap API call per repo) but does **not** re-run code-search discovery or the bubble chart — those are manual.
