#!/bin/sh

# Add the user pip install directories to the PATH and PYTHONPATH
##pip install --user flask flask_jwt_extended pint
export PATH=/var/user-packages/root/.local/bin:${PATH}

if [[ -z "$PYTHONPATH" ]];
then
	export PYTHONPATH=/var/user-packages/root/.local/lib/python3.7/site-packages:${PYTHONPATH}
else
	export PYTHONPATH=/var/user-packages/root/.local/lib/python3.7/site-packages
fi

if [[ -z "${TILED_API_KEY}" ]]; then
  export TILED_API_KEY=$(cat ~/.afl/tiled_api_key)
else
  export TILED_API_KEY="${TILED_API_KEY}"
fi

if [[ -z "${AFL_SYSTEM_SERIAL}" ]]; then
  export AFL_SYSTEM_SERIAL=$(cat ~/.afl/system_serial)
else
  export AFL_SYSTEM_SERIAL="${AFL_SYSTEM_SERIAL}"
fi

# add NistoRoboto to PYTHONPATH
# export PYTHONPATH=/root/user_storage/:${PYTHONPATH}
export PYTHONPATH=/root/user_storage/NistoRoboto:${PYTHONPATH}

# add user packages
export PATH=/data/packages/usr/local/bin:${PATH}
export CPATH=/data/packages/usr/local/include:${CPATH}
export LIBRARY_PATH=/data/packages/usr/local/lib:${LIBRARY_PATH}
export LD_LIBRARY_PATH=/data/packages/usr/local/lib:${LD_LIBRARY_PATH}

export NISTOROBOTO_CUSTOM_LABWARE=/root/custom_beta/
export OT_SMOOTHIE_ID=AMA 
export RUNNING_ON_PI=true

# cd /root/user_storage/
cd /root/user_storage/NistoRoboto
git pull
python AFL/automation/prepare/OT2_Driver.py
