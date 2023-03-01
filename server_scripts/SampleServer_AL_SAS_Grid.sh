#!/bin/bash -i

git config --global credential.helper store

conda activate afl_agent

cd ~/NistoRoboto/
git pull

python ~/NistoRoboto/server_scripts/SampleServer_AL_SAS_Grid.py
