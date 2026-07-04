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
# Add a new paper by DOI (updates inputs/publications.csv)
openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558"

# Collect all stats (citations, downloads, zenodo, plot)
openff-stats run-all

# Individual collection steps
openff-stats citations
openff-stats downloads
openff-stats zenodo-citations
openff-stats plot-downloads

# GitHub repo search (requires GITHUB_TOKEN env var)
openff-stats github-repos

# Refresh Scholar cluster IDs
openff-stats scholar-clusters

# Discovery (outputs require human review before use)
openff-stats discover-publications --orcid-csv inputs/orcids.csv
openff-stats discover-packages
openff-stats discover-dependents          # conda-forge reverse deps of openff-toolkit
openff-stats discover-zenodo
```

All commands accept `--help` and most accept `--input`/`--output` path overrides.

## Architecture

This is a data pipeline with a clear two-phase structure:

**Phase 1 — Discovery** (run manually, output reviewed by human before use)
- Writes to `candidates/` directory
- After review, curated data is moved to `inputs/`

**Phase 2 — Collection** (automated, run by CI)
- Reads from `inputs/*.csv` (curated by human)
- Writes stats to `data/*.csv` and `data/plots/`

### Source modules (`src/openff_stats/`)

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Click entry point; all commands defined here with lazy imports |
| `publications.py` | ORCID/Crossref discovery; Scholar (Selenium), Crossref, ChemRxiv citation collection |
| `downloads.py` | conda-forge package discovery; Anaconda API + condastats download collection |
| `zenodo.py` | Zenodo record discovery; DataCite citation collection |
| `github.py` | GitHub code search for repos importing `openff.toolkit` (requires `GITHUB_TOKEN`) |
| `plotting.py` | Seaborn bar chart of downloads per year |

### Key data flows

- `inputs/publications.csv` → `publications.py` → `data/citations.csv`
  - Scholar scraping uses a shared headless Firefox driver (`_scholar_driver` global in `publications.py`); lazy-initialized, closed after collection
  - `scholar_cluster_id` (Google Scholar's internal ID) is needed for Scholar citation counts; manually found via Scholar's `cluster=` URL parameter or via `openff-stats scholar-clusters`
  - `force_field_paper` column in `inputs/publications.csv` controls per-subset summary stats printed at the end of `citations`

- `inputs/packages.csv` → `downloads.py` → `data/downloads.csv` + `data/downloads_yearly.csv`
  - Two parallel methods: Anaconda API (most current totals) and condastats (has monthly/yearly breakdown)
  - `category` column is `openff` or `competitor`; only `openff` packages are summed in totals

- `inputs/zenodo.csv` → `zenodo.py` → `data/zenodo_citations.csv`

### CI

GitHub Actions (`.github/workflows/gh-ci.yaml`) is triggered manually (`workflow_dispatch`) and runs `openff-stats run-all`, then commits updated `data/` and `README.md` (date stamp) back to `main`.
