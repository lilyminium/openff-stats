#!/bin/bash

source ~/.bashrc

micromamba activate condastats

python get-crossref-citation-stats.py           \
    --input     ../data/publications.csv        \
    --output    ../data/citations.csv           \
    > get-crossref-citation-stats.log 2>&1