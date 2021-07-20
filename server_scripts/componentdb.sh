#!/bin/bash -i

git config --global credential.helper store

conda activate nistoroboto

cd /home/nistoroboto/NistoRoboto/NistoRoboto/componentDB/
git pull
export FLASK_APP=componentDB
export FLASK_ENV=development

python /home/nistoroboto/NistoRoboto/server_scripts/ComponentDB.py
