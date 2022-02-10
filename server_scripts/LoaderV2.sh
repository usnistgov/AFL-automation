#!/bin/bash -i

git config --global credential.helper store


cd ~/NistoRoboto/
git pull

python ~/NistoRoboto/server_scripts/LoaderV2Syringe.py
