#!/bin/bash -i

#git config --global credential.helper store

source /nfs/chess/sw/miniconda3_nist/bin/activate
conda activate 2110_nistoroboto

#cd ~/NistoRoboto/
#git pull

# python ~/beaucage/211012/NistoRoboto/server_scripts/CHESSID3B.py
# python ~/beaucage/211012/NistoRoboto/server_scripts/CHESSID3B.py
python /home/chess_id3b/currentaux/beaucage-2924-C/software/NistoRoboto/server_scripts/CHESSID3B.py
