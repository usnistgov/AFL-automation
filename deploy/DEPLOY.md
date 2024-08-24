
Max version supported on OT-2: 4.7.0.  Downgrade newer robots before setup via the Opentrons app.

Deployment instructions on Opentrons robots
============================================

1) Obtain SSH access to the OT-2 following instructions in the Opentrons docs.  SSH to root@(ot2-ip)
2) `cd /data/user_storage`
3) `git clone https://github.com/usnistgov/AFL-automation.git`
3.1) `pip install --user -e AFL-automation/` (may need to cd into directory)
4) `pip install --user flask<2.3 flask_jwt_extended flask_cors requests pint`
create two backwards-compatibility symlinks
5) `ln -s /data/user_storage /root/user_storage` 
6) `ln -s /data/user_storage/AFL-automation /data/user_storage/NistoRoboto`
7) copy custom_beta labware defintions from another machine to /data/labware/v2/custom_defitions
8) `ln -s /data/labware/v2/custom_definitions/custom_beta ~/ `
9) `ln -s /data/user_storage/AFL-automation/server_scripts /data/user_storage/server_scripts`


Deployment instructions on generic Rapberry Pis
===============================================

There are two ansible playbooks in this directory.  `setup-afl-python-env.yaml` does a number of tasks to turn a vanilla 
raspi image into an AFL module: clone this package, create a Python venv called aflpy, install some necessary apt packages,
install the requirements for all APIServers, etc.

`install-loader-extras.yaml` installs things needed on loaders in particular: LabJack drivers, specific Python packages, etc.

To run these:

1) Burn a Raspberry Pi SD card using the desktop software.  When doing so:
     - set the hostname according to the identity of the pi  (e.g., afl-loader), 
     - enable SSH access and set a password
2) Insert the SD card into the appropriate Pi and get it on a network.
3) Establish SSH communications:
     - `ssh pi@afl-loader.local`
       (enter password, then type exit - this is just verifying you can talk to it)
     - `ssh-copy-id pi@afl-loader.local`
       (this copies your private key to the pi for passwordless signin)
4) Put the machines you're running against into a file called hosts.ini like so:
```
[afl.pis]
afl-loader.local
```
4) Run the ansible playbooks against your new pi.
```
     ansible-playbook -i hosts.ini setup-afl-python-env.yaml
     ansible-playbook -i hosts.ini install-loader-extras.yaml
```
