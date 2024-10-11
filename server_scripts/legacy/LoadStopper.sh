#!/bin/bash -i

git config --global credential.helper store

conda activate afl_agent

cd ~/AFL-automation/
git pull

python server_scripts/LoadStopper.py
