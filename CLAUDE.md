# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Preferred (pixi):

```bash
pixi install
pixi run openff-stats ...
```

Alternative (conda; also what CI uses):

```bash
conda env create -f environment.yaml
conda activate openff-stats
# environment.yaml installs the package in editable mode via pip install -e .
```

Google Scholar scraping requires Firefox and geckodriver (hardcoded for macOS).

## Common commands

```bash
# Add a source (each fetches metadata, dedupes across ALL groups, appends to
# inputs/<kind>/<group>.csv — the filename is the group classification)
openff-stats add-doi DOI... --file dois.txt --group NAME   # auto-routes: 10.5281/zenodo.* → zenodo, else publication
openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558" --group force-field   # optionally --scholar
openff-stats add-github-repo openforcefield/openff-toolkit --group openff-toolkit   # status=manual; --group = package it imports
openff-stats add-zenodo 10.5281/zenodo.18842670 --group qcsubmit

# Google Scholar lookup by DOI (find/store scholar_cluster_id)
openff-stats scholar-lookup "10.1021/acs.jpcb.4c01558" --save   # one DOI
openff-stats scholar-clusters                                   # fill all missing, bulk

# Collect all stats (citations, downloads, zenodo, github stars);
# every collector prints cumulative sums per group (group = input filename)
openff-stats run-all

# Individual collection steps
openff-stats citations
openff-stats downloads
openff-stats zenodo-citations
openff-stats github-stars                 # requires GITHUB_TOKEN; per-group repo-import counts

# GitHub topic descriptions (manual: needs reviewed category column)
openff-stats github-descriptions          # requires GITHUB_TOKEN

# GitHub repo discovery: script-verified, writes straight to data/github_repos/<package>.csv
# (status=auto/exclude, evidence in notes) — no candidates/ review step, unlike discover-* below
openff-stats discover-github-repos                     # sweep all packages in inputs/github_packages.csv
openff-stats discover-github-repos --package descent   # one package (import name + search mode from the CSV)
openff-stats classify-repos               # re-tag data/github_repo_stars.csv offline (e.g. after editing the blacklist)

# Optional bulk discovery → candidates/ (gitignored, human-reviewed)
openff-stats discover-publications --orcid-csv inputs/orcids.csv
openff-stats discover-packages
openff-stats discover-dependents          # conda-forge reverse deps of openff-toolkit
openff-stats discover-zenodo
```

All commands accept `--help` and most accept `--input`/`--output` path overrides.

## Recipe: get citations for a list of DOIs

Deterministic, judgement-free sequence — safe to delegate to a cheaper
(Sonnet-level) agent. No routing decisions needed: `add-doi` detects Zenodo
DOIs from the DOI itself.

1. Put the DOIs in a text file, one per line (blank lines and `#` comments ignored).
2. `openff-stats add-doi --file FILE`
   - DOIs starting with `10.5281/zenodo.` → `inputs/zenodo/<group>.csv`; all
     others → `inputs/publications/<group>.csv` (Crossref metadata). Pass
     `--group NAME` to classify (default `general`); dedup spans all groups.
   - Idempotent: already-present DOIs are skipped; failures don't stop the
     batch and are listed at the end. Exit code 0 means all DOIs processed.
3. `openff-stats zenodo-citations` → `data/zenodo_citations.csv`
   (DataCite API only, no browser needed).
4. `openff-stats citations` → `data/citations.csv`
   - Crossref counts always work (plain HTTP). Scholar counts need
     Firefox + geckodriver and a `scholar_cluster_id` per row; on any Scholar
     failure the count is just left blank (`None`) — the command still succeeds.
     Report `crossref_citations` if `scholar_citations` is blank.
5. Read the results: `data/citations.csv` (`crossref_citations`,
   `scholar_citations`) and `data/zenodo_citations.csv` (`citation_count`).

## Architecture

Every source is a **manually curated** CSV in `inputs/`, with one exception:
GitHub repo lists live in `data/github_repos/` because they're script-generated
measurements, not hand input. Collection reads the curated inputs (plus, for
GitHub, the script-generated repo lists) and writes stats to `data/`. Discovery
is optional and normally writes `candidates/` for human review — except GitHub
discovery, which verifies each candidate itself and writes straight to
`data/github_repos/`, never touching `candidates/`.

**Curation** (manual)
- `add-*` commands append one row to a curated CSV (metadata fetched, deduped across all groups): `inputs/<kind>/<group>.csv` for DOIs/Zenodo, `data/github_repos/<group>.csv` (status=manual) for GitHub repos
- `discover-*` commands write `candidates/*.csv` (gitignored) for review — except `discover-github-repos`, which writes verified rows straight to `data/github_repos/<package>.csv` (status=auto/exclude), no review step

**Collection** (automated, run by CI)
- Reads `inputs/<kind>/*.csv` (or `data/github_repos/*.csv` for GitHub) → writes `data/*.csv` (rows tagged with `group` = filename)

### Source modules (`src/openff_stats/`)

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Click entry point; all commands defined here with lazy imports |
| `publications.py` | `add-publication-doi`, `scholar-lookup`; ORCID/Crossref discovery; Scholar (Selenium) / Crossref / ChemRxiv citation collection |
| `downloads.py` | conda-forge package + dependent-tree discovery; Anaconda API + condastats download collection |
| `zenodo.py` | `add-zenodo`; Zenodo discovery; DataCite citation collection |
| `github.py` | `add-github-repo`; curated-list loader; star/description collection; script-verified code-search discovery + `classify-repos` (requires `GITHUB_TOKEN` for discovery/stars) |

### Key data flows

Every input kind is a directory of CSVs; the filename is the group
classification (`curated.load_groups` tags rows with `group`). Collection
outputs carry the `group` column and print cumulative sums per group.

- `inputs/publications/*.csv` → `publications.py` → `data/citations.csv`
  - Scholar scraping uses a shared headless Firefox driver (`_scholar_driver` global in `publications.py`); lazy-initialized, closed after collection
  - `scholar_cluster_id` (Google Scholar's internal ID) is needed for Scholar citation counts. Find it by DOI with `scholar-lookup` (one DOI) or `scholar-clusters` (bulk-fill every missing one); both share `_match_scholar()` — search Scholar by DOI, fall back to the title, validate the hit against the title, and parse the cluster ID from each result link's `data-clk` `d=<id>` field before accepting it
  - the `force-field` group (file `force-field.csv`) is the force-field-papers subset in the summary

- `inputs/packages/*.csv` → `downloads.py` → `data/downloads.csv` + `data/downloads_yearly.csv`
  - Two parallel methods: Anaconda API (most current totals) and condastats (has monthly/yearly breakdown)
  - groups are `openff` / `competitor` (filenames); download sums are printed per group

- `data/github_repos/*.csv` → `github.py` → `data/github_repo_stars.csv` (+ descriptions)
  - group = the package the repos import (e.g. `openff-toolkit.csv`); files are script-generated by `discover-github-repos` from `inputs/github_packages.csv` (package, import_name, search_mode), plus manual rows via `add-github-repo`
  - `status` is `auto` (verified evidence recorded in `notes`) / `exclude` (matched search, no evidence — kept for the record) / `manual` (added via `add-github-repo`); `load_curated_repos()` drops rows with `status == exclude`
  - `github-stars` prints per-group repo-import counts and star sums; `classify-repos` re-applies `valid`/`reason` tagging from `inputs/github_owner_blacklist.csv` offline

- `inputs/zenodo/*.csv` → `zenodo.py` → `data/zenodo_citations.csv`

### CI

GitHub Actions (`.github/workflows/gh-ci.yaml`) is triggered manually (`workflow_dispatch`) and runs `openff-stats run-all`, then commits updated `data/` and `README.md` (date stamp) back to `main`. `run-all` collects GitHub *stars* for the curated repo list (one cheap API call per repo) but does **not** re-run code-search discovery — that's manual.
