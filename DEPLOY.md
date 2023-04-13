
Max version supported on OT-2: 4.7.0.  Downgrade newer robots before setup via the Opentrons app.

Deployment instructions on Opentrons robots
============================================

1) Obtain SSH access to the OT-2 following instructions in the Opentrons docs.  SSH to root@(ot2-ip)
2) # cd /data/user_storage
3) # git clone https://github.com/usnistgov/AFL-automation.git
3.1) # pip install -e AFL-automation/ #may need to cd into directory
4) # pip install --user flask flask_jwt_extended flask_cors requests pint
create two backwards-compatibility symlinks
5) # ln -s /data/user_storage /root/user_storage 
6) # ln -s /data/user_storage/AFL-automation /data/user_storage/NistoRoboto
7) copy custom_beta labware defintions from another machine to /data/labware/v2/custom_defitions
8) ln -s /data/labware/v2/custom_definitions/custom_beta ~/
9) ln -s /data/user_storage/AFL-automation/server_scripts /data/user_storage/server_scripts

