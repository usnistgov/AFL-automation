#!/bin/sh

# Add the user pip install directories to the PATH and PYTHONPATH
##pip install --user flask flask_jwt_extended
export PATH=/var/user-packages/root/.local/bin:${PATH}

if [[ -z "$PYTHONPATH" ]];
then
	export PYTHONPATH=/var/user-packages/root/.local/lib/python3.7/site-packages:${PYTHONPATH}
else
	export PYTHONPATH=/var/user-packages/root/.local/lib/python3.7/site-packages
fi

# add NistoRoboto to PYTHONPATH
export PYTHONPATH=/root/user_storage/:${PYTHONPATH}

# add user packages
export PATH=/data/packages/usr/local/bin:${PATH}
export CPATH=/data/packages/usr/local/include:${CPATH}
export LIBRARY_PATH=/data/packages/usr/local/lib:${LIBRARY_PATH}
export LD_LIBRARY_PATH=/data/packages/usr/local/lib:${LD_LIBRARY_PATH}

export NISTOROBOTO_CUSTOM_LABWARE=/root/user_storage/custom_labware

cd /root/user_storage/
python server_scripts/OT2.py
