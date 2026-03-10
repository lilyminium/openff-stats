# data/

Output files from the openff-stats pipeline. Last updated: 2026-03-04.

## Files

| File | Description |
|------|-------------|
| `citations.csv` | Per-paper citation counts (Crossref, Google Scholar, ChemRxiv) |
| `downloads.csv` | Total conda-forge downloads per package |
| `downloads_yearly.csv` | Per-package per-year downloads (condastats) |
| `plots/` | Generated figures (e.g. downloads per year bar chart) |

## Citation counts

> **Note:** Google Scholar counts are manually verified and tend to be higher than Crossref
> (Scholar includes grey literature and preprints). Numbers fluctuate over time.

### All publications (27 papers)

| Source | Total citations |
|--------|----------------|
| Crossref | 991 |
| Google Scholar | 1,468 |

### Force field papers only (SMIRNOFF · Parsley · Sage · AshGC)

| Paper | Year | Crossref | Scholar |
|-------|------|----------|---------|
| Escaping Atom Types (SMIRNOFF) | 2018 | 145 | 223 |
| Parsley v1.0.0 | 2021 | 124 | 191 |
| Sage 2.0.0 | 2023 | 143 | 207 |
| Sage 2.3.0 + AshGC | 2026 | 0 | 1 |
| **Total** | | **412** | **622** |

## Download counts

OpenFF conda-forge packages (excludes competitor packages tracked for comparison).

| Method | Total downloads |
|--------|----------------|
| Anaconda API (`anaconda_total`) | 6,302,479 |
| condastats API (`condastats_total`) | 8,817,118 |

> **Caveat:** These numbers vastly overcount real installs. OpenFF packages depend on each
> other, so a single user install pulls in many packages simultaneously. CI/CD pipelines
> also contribute heavily. The true user count is likely 5–10× lower than these figures.
