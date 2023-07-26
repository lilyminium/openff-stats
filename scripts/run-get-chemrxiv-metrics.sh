#!/bin/bash

source ~/.bashrc

micromamba activate condastats

python get-chemrxiv-stats.py                    \
    --input     ../inputs/chemrxiv.csv          \
    --output    ../data/chemrxiv-metrics.csv    \
    > get-chemrxiv-metrics.log 2>&1