#!/bin/bash -i

git config --global credential.helper store

conda activate afl_agent

cd ~/NistoRoboto/
git pull

python ~/NistoRoboto/server_scripts/SAS_Agent.py
