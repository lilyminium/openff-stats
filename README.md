# openff-stats

Stats for OpenFF software packages and publications.

**Note: I've only manually checked the Google Scholar numbers for citations.**
Google Scholar citations require Selenium + Firefox; this is essentially
hardcoded to work on my machine (tm), no guarantees it'll work for you.

Date last updated: 2026-03-04

## How it works

Every source is a **manually curated** CSV in `inputs/`. Collection commands
read those files and write stats to `data/`. Nothing is scraped into the
pipeline automatically — you decide what goes in `inputs/`.

```
inputs/publications.csv   ← papers (DOIs) to track citations for
inputs/packages.csv       ← conda-forge packages to track downloads for
inputs/zenodo.csv         ← Zenodo records to track DataCite citations for
inputs/github_repos.csv   ← GitHub repos that use openff-toolkit

data/citations.csv             ← Crossref / Scholar / ChemRxiv citation counts
data/downloads.csv             ← total downloads per package
data/downloads_yearly.csv      ← per-package per-year downloads
data/zenodo_citations.csv      ← DataCite citation counts for Zenodo records
data/github_repo_stars.csv     ← star counts for the curated repos
data/plots/…                   ← charts
```

## How to add a new source

One command per source type. Each fetches metadata, de-duplicates, and appends
a row to the curated CSV — so adding a source is a one-liner, and you can always
hand-edit the CSV afterwards.

```bash
# A paper (Crossref metadata). Add --scholar to also fill the Scholar cluster ID.
openff-stats add-publication-doi "10.1021/acs.jpcb.4c01558"

# A GitHub repo (OWNER/REPO or a github.com URL).
openff-stats add-github-repo openforcefield/openff-toolkit

# A Zenodo record (numeric ID, DOI, or record URL).
openff-stats add-zenodo 10.5281/zenodo.18842670

# A conda-forge package: edit inputs/packages.csv directly (package,category).
```

Then run `openff-stats run-all` to refresh the stats.

### Google Scholar lookup by DOI

Scholar citation counts need a `scholar_cluster_id` per paper (Scholar's
internal ID for the group of all versions of a paper). Look one up by DOI:

```bash
# One DOI — print the matched paper, its cluster ID, and Cited-by count:
openff-stats scholar-lookup "10.1021/acs.jpcb.4c01558"

# ...and write the cluster ID into inputs/publications.csv:
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

| File | Columns |
|------|---------|
| `publications.csv` | `DOI, force_field_paper, title, authors, year, scholar_cluster_id, chemrxiv_id` |
| `packages.csv` | `package, category` (`category` is `openff` or `competitor`) |
| `zenodo.csv` | `zenodo_id, doi, title, creators, publication_year, resource_type` |
| `github_repos.csv` | `repo, url, status, notes` |

`scholar_cluster_id` / `chemrxiv_id` may be blank. In `github_repos.csv`,
`status` is `manual` (you added it), `auto` (seeded from discovery), or
`exclude` (kept for the record but skipped by collection and plots).
`force_field_paper=True` marks papers included in the force-field-only summary
totals.

## Data collection

```bash
openff-stats citations          # Crossref + Google Scholar + ChemRxiv
openff-stats downloads          # conda-forge downloads (Anaconda + condastats)
openff-stats zenodo-citations   # DataCite citations for Zenodo records
openff-stats github-stars       # star counts for curated repos (needs GITHUB_TOKEN)
openff-stats plot-downloads     # downloads-per-year bar chart

openff-stats run-all            # everything above + the downloads plot
```

All commands take `--help` and accept `--input` / `--output` overrides.

### GitHub bubble chart

The GitHub bubble chart needs a reviewed topic category per repo, so it is a
manual two-step (not part of `run-all`):

```bash
openff-stats github-stars                         # star counts (needs GITHUB_TOKEN)
openff-stats github-descriptions                  # descriptions + auto category
# review the `category` column in data/github_repo_descriptions.csv, then:
openff-stats plot-github-bubbles
```

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

`discover-github-repos` flags repos not already in `inputs/github_repos.csv`
(sorted first) so review is a quick scan of the top rows.

## Please read these caveats before using these numbers

### Download counts

Please take these download counts with a gigantic pile of salt. They are *not*
a reflection of user numbers, and vastly overcount "real" installs:

- Many OpenFF packages depend on each other, so downloading one pulls in
  others. The "total OpenFF conda-forge downloads" simply sums all downloads
  across all packages, so it is likely inflated at least 5-fold, probably ~10.
- Many, perhaps most, downloads are just CI and tests.

Methodology note: where there are two versions of a package (e.g.
`openff-toolkit` and `openff-toolkit-base`), only the `-base` counts are used,
so at least those are not double counted.

### Citations

We use Google Scholar and Crossref numbers because they're easy. Of Scholar,
Crossref, and Scopus, Scholar tends to have the highest citation numbers. We
have anecdotally seen Scholar numbers fluctuate depending on when we look,
possibly from behind-the-scenes algorithm updates. The date is above.

| Source | Notes |
|--------|-------|
| Crossref (`crossref_citations`) | DOI-to-DOI citation links within Crossref. Reliable but lower than Scholar. |
| Google Scholar (`scholar_citations`) | Scraped from Scholar cluster pages via `scholar_cluster_id`. Higher counts; fragile (CAPTCHAs). |
| ChemRxiv (`chemrxiv_*`) | From the ChemRxiv public API, via `chemrxiv_id`. Preprints only. |
| DataCite (`citation_count`) | For Zenodo records, via `api.datacite.org`. |

## Installation

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
stamp back to `main`. Discovery and the GitHub bubble chart are not run in CI
(they need human review).
