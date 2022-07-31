#!/bin/bash -i

git config --global credential.helper store

conda activate nistoroboto

cd ~/NistoRoboto/
git pull

python ~/NistoRoboto/server_scripts/SampleServer_SAS.py
