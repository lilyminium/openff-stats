#!/bin/bash

source ~/.bashrc

micromamba activate condastats

python get-crossref-citation-stats.py           \
    --input     ../inputs/crossref.csv          \
    --output    ../data/citations.csv           \
    > get-crossref-citation-stats.log 2>&1