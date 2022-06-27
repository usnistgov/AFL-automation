#!/bin/bash -i

git config --global credential.helper store

conda activate afl_agent
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda-11.0/lib64/

cd ~/NistoRoboto/
git pull

python ~/AFL-automation/server_scripts/SAS_Agent.py
