#!/bin/bash -i

#git config --global credential.helper store

source /nfs/chess/sw/miniconda3_nist/bin/activate
conda activate 2211_nistoroboto

echo `which python`

#cd ~/NistoRoboto/
#git pull

# python ~/beaucage/beaucage-2924-D/NistoRoboto/server_scripts/CHESSID3B.py
python ~/beaucage/current/afl-automation/AFL/automation/instrument/CHESSID3B.py
