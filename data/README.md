# data/

Output files from the openff-stats pipeline. Last updated: 2026-07-09.
See the top-level README's "Methodology and caveats" section for how each
number is measured. Every table below is broken down by group — the group
is the `inputs/<kind>/<group>.csv` file a source is curated in.

## Files

| File | Description |
|------|-------------|
| `citations.csv` | Per-paper citation counts (Crossref, OpenAlex, Semantic Scholar, Google Scholar, ChemRxiv), with group |
| `zenodo_citations.csv` | DataCite citations for Zenodo records, long form (one row per record-year; `citation_count` = record total) |
| `downloads.csv` | Total conda-forge downloads per package (Anaconda API + condastats) |
| `downloads_yearly.csv` | Per-package per-year downloads (condastats) |
| `github_repos/<package>.csv` | Script-generated repo lists per package (repo, url, status, notes), with per-row verification evidence in `notes` |
| `github_repo_stars.csv` | Star counts for the curated repos, with group (group = package imported) |
| `dep_tree.csv` | conda-forge reverse-dependency tree rooted at openff-toolkit |

## Citation counts

> **Note:** Google Scholar counts are manually spot-checked and tend to be
> the highest (Scholar includes grey literature and preprints); OpenAlex
> typically sits between Crossref and Scholar. Numbers fluctuate over time.

### Per group (28 papers)

| Group | Papers | Crossref | OpenAlex | Semantic Scholar | Google Scholar |
|-------|--------|----------|----------|------------------|----------------|
| force-field | 4 | 463 | 591 | 342 | 690 |
| general | 24 | 667 | 738 | 556 | 962 |
| **Total** | **28** | **1,130** | **1,329** | **898** | **1,652** |

Semantic Scholar covers 22/28 papers; Google Scholar resolved 27/28 on the
last run. The curated list has since grown to 36 papers; the newest
additions are counted from the next `openff-stats citations` run.

### Force field papers (SMIRNOFF · Parsley · Sage · AshGC)

| Paper | Year | Crossref | Scholar |
|-------|------|----------|---------|
| Escaping Atom Types (SMIRNOFF) | 2018 | 154 | 239 |
| Parsley v1.0.0 | 2021 | 133 | 204 |
| Sage 2.0.0 | 2023 | 176 | 244 |
| Sage 2.3.0 + AshGC | 2026 | 0 | 3 |
| **Total** | | **463** | **690** |

### Software Papers

| Paper | Year | Crossref | Scholar |
|-------|------|----------|---------|
| Escaping Atom Types (Toolkit) | 2018 | 154 | 239 |
| BespokeFit (QCSubmit) | 2022 | 37 | 72 |
| **Total** | | **181** | **311** |

## Zenodo citations (DataCite)

| Group | Records | Citations |
|-------|---------|-----------|
| general | 232 | 22 |
| openff-toolkit | 65 | 19 |
| qcsubmit | 18 | 7 |
| yammbs | 2 | 2 |
| **Total** | **317** | **50** |

## Download counts

Quote the **condastats** column, with its reference date — e.g. "10.1M
downloads as of 2026-07 per anaconda-package-data". The Anaconda API
counters undercount modern `.conda`-format downloads by ~1.5× (and
overcount mirror/bot traffic on low-volume packages); see the methodology
section of the top-level README for the spot-check.

| Group | Packages | condastats (as of 2026-07) | Anaconda API |
|-------|----------|----------------------------|--------------|
| openff | 15 | 10,072,572 | 7,254,585 |
| competitor | 2 | 5,155,888 | 4,941,993 |

### Average monthly users per year

| Year | Group | Total Downloads | Avg Monthly | 10% of Monthly |
|------|-------|-----------------|-------------|----------------|
| 2019 | competitor | 16,522 | 1,377 | 138 |
| 2020 | competitor | 123,568 | 10,297 | 1,030 |
| 2021 | competitor | 584,737 | 48,728 | 4,873 |
| 2021 | openff | 261,653 | 21,804 | 2,180 |
| 2022 | competitor | 610,264 | 50,855 | 5,086 |
| 2022 | openff | 571,635 | 47,636 | 4,764 |
| 2023 | competitor | 709,601 | 59,133 | 5,913 |
| 2023 | openff | 1,370,440 | 114,203 | 11,420 |
| 2024 | competitor | 1,073,923 | 89,494 | 8,949 |
| 2024 | openff | 2,499,397 | 208,283 | 20,828 |
| 2025 | competitor | 1,440,190 | 120,016 | 12,002 |
| 2025 | openff | 3,652,277 | 304,356 | 30,436 |
| 2026 | competitor | 597,083 | 85,298 | 8,530 |
| 2026 | openff | 1,722,728 | 246,104 | 24,610 |

### Average monthly users per year by package

#### 2025

**Competitor packages (2025):**

| Package | Downloads | Avg Monthly | 10% of Monthly |
|---------|-----------|-------------|----------------|
| ambertools | 697,426 | 58,119 | 5,812 |
| parmed | 742,764 | 61,897 | 6,190 |

**Openff packages (2025):**

| Package | Downloads | Avg Monthly | 10% of Monthly |
|---------|-----------|-------------|----------------|
| descent | 1,447 | 121 | 12 |
| openff-amber-ff-ports | 507,954 | 42,330 | 4,233 |
| openff-bespokefit | 12,566 | 1,047 | 105 |
| openff-evaluator-base | 4,177 | 348 | 35 |
| openff-forcefields | 514,924 | 42,910 | 4,291 |
| openff-fragmenter-base | 28,616 | 2,385 | 238 |
| openff-interchange-base | 473,612 | 39,468 | 3,947 |
| openff-models | 260,631 | 21,719 | 2,172 |
| openff-nagl-base | 100,073 | 8,339 | 834 |
| openff-nagl-models | 94,245 | 7,854 | 785 |
| openff-qcsubmit | 32,375 | 2,698 | 270 |
| openff-recharge | 24,318 | 2,026 | 203 |
| openff-toolkit-base | 526,029 | 43,836 | 4,384 |
| openff-toolkit-examples | 10,733 | 894 | 89 |
| openff-units | 529,030 | 44,086 | 4,409 |
| openff-utilities | 531,547 | 44,296 | 4,430 |

> **Caveat:** These numbers vastly overcount real installs. OpenFF packages depend on each
> other, so a single user install pulls in many packages simultaneously. CI/CD pipelines
> also contribute heavily. The true user count is likely 5–10× lower than these figures.

## GitHub repos importing OpenFF packages

The repo lists in `data/github_repos/` are fully script-generated
(`openff-stats discover-github-repos`): code-search candidates are verified
against the files that matched (dependency manifests / real import
statements) and tagged `status=auto` or `exclude` with the evidence recorded
per row. Only `auto`/`manual` rows are counted below.

| Group (package imported) | Repos | External repos | Stars | External stars | With Python Installation |
|--------------------------|-------|----------------|-------|----------------|--------------------|
| openff-toolkit | 660 | 544 | 14,067 | 12,618 | 249 |
| openff-qcsubmit | 73 | 1 | 364 | 8 | 19 |
| descent | 4 | 0 | 7 | 0 | 0 |
| yammbs | 28 | 0 | 39 | 0 | 8 |
| **Total** | **765** | **545** | **14,477** | **12,626** | **276** |

> **Caveat:** "External" counts exclude repos owned by the OpenFF org and core
> maintainers (`external_reason` = "self" — these measure our own activity, not
> external adoption), `conda-forge` packaging repos (`"meta"`), repos listed
> in a higher-priority group (`"duplicate"` — a repo importing several
> tracked packages counts once, in the first group per
> `inputs/github_packages.csv`, so later rows read as *additional* adoption),
> and forks outshone by a family member (`"fork"`). The full rows remain in
> `github_repo_stars.csv` with an `external_reason` column; quote the external counts,
> not the raw totals, when talking about external adoption.

> **Note on Python configs:** The `github_repo_stars.csv` file includes a
> `has_python_config` column indicating whether each repo contains a
> `setup.py` or `pyproject.toml` file. This signals a Python package and
> can be used to filter for only "mature" repos that have adopted modern
> packaging (pyproject.toml) or traditional setup.py.

> **Note on descent:** its generic name makes GitHub code search unusable
> (`gradient-descent` etc. match a `descent` query), so it is searched in
> conda environment files only (`search_mode=environment-only` in
> `inputs/github_packages.csv`) — its numbers are a floor, and its known
> external users also import openff-toolkit, so they are counted there.
