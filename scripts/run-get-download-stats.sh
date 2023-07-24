#!/bin/bash

source ~/.bashrc

micromamba activate condastats

python get-anaconda-downloads.py                          \
    --package           "openff-toolkit"                  \
    --package           "openff-evaluator"                \
    --package           "openff-interchange"              \
    --package           "openff-bespokefit"               \
    --package           "openff-recharge"                 \
    --package           "openff-qcsubmit"                 \
    --package           "openff-fragmenter"               \
    --package           "openff-utilities"                \
    --package           "openff-units"                    \
    --package           "openff-models"                   \
    --package           "openff-nagl"                     \
    --output            "../data/openff-software-downloads.csv"  \
    > get-openff-software-downloads.log 2>&1


python get-anaconda-downloads.py                          \
    --package           "openff-forcefields"                \
    --output            "../data/openff-forcefields-downloads.csv" \
    > get-openff-forcefields-downloads.log 2>&1