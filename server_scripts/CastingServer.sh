#!/bin/bash -i

git config --global credential.helper store

conda activate afl_agent

cd ~/AFL-automation/
git pull

python ~/AFL-automation/AFL/automation/sample/CastingServer.py
