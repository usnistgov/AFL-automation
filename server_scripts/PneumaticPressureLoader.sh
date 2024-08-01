#!/bin/bash -i

git config --global credential.helper store


cd ~/AFL-automation/
git pull

python ~/AFL-automation/AFL/automation/loading/PneumaticPressureSampleCell.py
