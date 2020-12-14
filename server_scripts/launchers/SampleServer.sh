#!/bin/bash -i

git config --global credential.helper store

conda activate nistoroboto

cd ~/nistoroboto/
git pull

python ~/nistoroboto/server_scripts/SampleServer.py
