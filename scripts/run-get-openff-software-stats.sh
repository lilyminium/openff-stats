#!/bin/zsh

source ~/.zshrc

micromamba activate condastats

python get-openff-software-stats.py                       \
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
    --output-directory  "../data/openff-software-stats/"  \
    > get-openff-software-stats.log 2>&1


python get-openff-software-stats.py                         \
    --package           "openff-forcefields"                \
    --output-directory  "../data/openff-forcefields-stats/" \
    > get-openff-forcefields-stats.log 2>&1