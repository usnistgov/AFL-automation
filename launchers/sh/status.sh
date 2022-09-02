#!/bin/bash

if [ "$1" == "all" ] || [ "$1" == "loader" ] ; then
ssh piloader2 -f 'screen -ls'
fi

if [ "$1" == "all" ] || [ "$1" == "robot" ] ; then
#ssh piot2 -f 'screen -d -m -S OT2Server /root/user_storage/server_scripts/launchers/OT2Server.sh '
ssh piot2 -f 'screen -ls'
fi

if [ "$1" == "all" ] || [ "$1" == "sample" ] ; then
screen -ls
fi

if [ "$1" == "help" ] || [ "$1" == "usage" ] || [ -z $1 ] ; then
echo 'Usage: status.sh loader | robot | sample | all (| help)'
fi

