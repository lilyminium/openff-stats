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
scripts/get-crossref-citation-stats.log:Total citations: 483
scripts/get-openff-forcefields-downloads.log:Total downloads: 289473
scripts/get-openff-forcefields-stats.log:Total downloads: 246055
scripts/get-openff-software-downloads.log:Total downloads: 928312
scripts/get-openff-software-stats.log:Total downloads: 567702
```
