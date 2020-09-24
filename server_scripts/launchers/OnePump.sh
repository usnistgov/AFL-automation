#!/bin/bash -i

git config --global credential.helper store

source activate nistoroboto

cd ~/NistoRoboto/
git pull

python ~/NistoRoboto/server_scripts/OnePump.py
