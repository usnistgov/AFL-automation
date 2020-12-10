#!/bin/bash

if [ "$1" == "all" ] | [ "$1" == "loader" ] ; then
ssh piloader2 -f 'screen -d -m  -S LoaderServer /home/pi/NistoRoboto/server_scripts/launchers/OnePumpCetoni.sh '
echo 'Started LoaderServer...'
fi

if [ "$1" == "all" ] | [ "$1" == "robot" ] ; then
ssh piot2 -f 'screen -d -m  -S OT2Server /root/user_storage/server_scripts/launchers/OT2Server.sh '
echo 'Started OT2Server...'
fi

if [ "$1" == "all" ] | [ "$1" == "sample" ] ; then
screen -d -m -S SampleServer /home/nistoroboto/NistoRoboto/server_scripts/launchers/SampleServer.sh 
echo 'Started SampleServer...'
fi

if [ "$1" == "help" ] | [ "$1" == "usage" ] | [ -z $1 ] ; then
echo 'Usage: start.sh loader | robot | sample | all (| help)'
fi

