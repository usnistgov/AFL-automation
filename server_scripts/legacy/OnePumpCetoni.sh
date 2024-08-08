#!/bin/bash -i

LD_LIBRARY_PATH=~/QmixSDK_Raspi/lib:"$LD_LIBRARY_PATH"
PYTHONPATH=~/QmixSDK_Raspi/python:"$PYTHONPATH"
modprobe ixxat_usb2can
export LD_LIBRARY_PATH
export PYTHONPATH

git config --global credential.helper store

sudo ip link set can0 up type can bitrate 1000000
sudo ip link set txqueuelen 10 dev can0

source activate nistoroboto
conda activate nistoroboto 
cd ~/NistoRoboto/
git pull

python3 ~/NistoRoboto/server_scripts/OnePumpCetoni.py
