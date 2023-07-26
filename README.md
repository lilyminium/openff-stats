# openff-stats
Stats for OpenFF software and FFs

The `data/` directory contains the outputs of the `scripts/` directory.

Each Python script (`*.py`) has an accompanying shell script (`*.sh`)
that demonstrates how to run it, as well as a log file (`*.log`)
demonstrating the outputs. The shell scripts should be modified
to run on your own machine, e.g. by changing the shell to `bash`
and perhaps using `conda` or `mamba` in place of `micromamba`.

```bash
$ grep Total scripts/*.log
scripts/get-ambertools-downloads.log:Total downloads: 1087098
scripts/get-chemrxiv-metrics.log:Total Abstract Views: 60812
scripts/get-chemrxiv-metrics.log:Total Citations: 5
scripts/get-chemrxiv-metrics.log:Total Content Downloads: 14012
scripts/get-crossref-citation-stats.log:Total citations: 483
scripts/get-openff-forcefields-downloads.log:Total downloads: 290921
scripts/get-openff-forcefields-stats.log:Total downloads: 246055
scripts/get-openff-software-downloads.log:Total downloads: 935230
scripts/get-openff-software-stats.log:Total downloads: 567702
scripts/get-scholar-citation-stats.log:Total citations: 727
```

## Difference between openff-forcefields-stats and openff-forcefields-downloads (and corresponding openff-software)

openff-xx-stats uses the more robust `condastats` API to get download data.
This is updated on a periodic basis, but as of July 2023 does not
include Python 3.10+.
(See https://github.com/ContinuumIO/anaconda-package-data/issues/41 for more).
That means it undercounts downloads.

openff-xx-downloads uses a fragile script to visit the Anaconda page
(e.g. https://anaconda.org/conda-forge/openff-toolkit) and parses the HTML
to get the total downloads listed. For now, this is likely the more
accurate figure, and it is likely updated more frequently than `anaconda-package-data`.


## Citations
Right now this uses Crossref to get citation data. This doesn't always
match up with how many citations are shown if you look at the individual
journal articles.

DataCite also has a queryable API for citations. Zenodo's API returns
download count, but no citations. A solution could be to parse HTML
as above.
