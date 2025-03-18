
Max version supported on OT-2: 4.7.0.  Downgrade newer robots before setup via the Opentrons app.

Deployment instructions on Opentrons robots
============================================

Setting up SSH Access
---------------------
https://support.opentrons.com/s/article/Setting-up-SSH-access-to-your-OT-2

https://support.opentrons.com/s/article/Connecting-to-your-OT-2-with-SSH#:~:text=Sometimes%20when%20you%20try%20to%20connect%20you,is%20blocking%20this%20connection%20like%20a%20firewall.

1) Generate a new ssh key if needed or desired. Resusing an old key is fine: `ssh-keygen -f ot2_ssh_key`
2) Ensure that you are connected to the robot on a link-local, 169.x.x.x subnet. If you modify the network settings, you need to restart the network interface and then the robot
3) curl -H 'Content-Type: application/json' -d "{\"key\":\"$(cat ot2_ssh_key.pub)\"}" ROBOT_IP:31950/server/ssh_keys
4) Ensure that `HostkeyAlgorithms +ssh-rsa` and `PubkeyAcceptedAlgorithms +ssh-rsa` are in your /etc/ssh/ssh_config
5) connect with ssh -i root@ROBOT_IP

Deploying AFL-Automation
------------------------

1) SSH to root@(ot2-ip)
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
[all:vars]
ansible_connection=ssh
ansible_user=pi
[afl.pis]
afl-loader.local
```
4) Run the ansible playbooks against your new pi.
```
     ansible-playbook -i hosts.ini setup-afl-python-env.yaml
     ansible-playbook -i hosts.ini install-loader-extras.yaml
```
