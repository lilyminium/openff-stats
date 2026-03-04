#!/bin/bash

source ~/.bashrc

micromamba activate condastats

python get-scholar-citation-stats.py            \
    --input     ../inputs/scholar.csv          \
    --output    ../data/google-scholar.csv           \
    > get-scholar-citation-stats.log 2>&1