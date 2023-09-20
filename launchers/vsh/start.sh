#!/bin/bash

if [ "$1" == "all" ] | [ "$1" == "loader" ] ; then
screen -d -m  -S VirtualLoaderServer ~/AFL-automation/server_scripts/virtual_instrument/DummyLoader.sh 
#screen -S VirtualLoaderServer ./DummyLoader.sh
echo 'Started VirtualLoaderServer...'
fi

if [ "$1" == "all" ] | [ "$1" == "robot" ] ; then
screen -d -m -S VirtualOT2Server ~/AFL-automation/server_scripts/virtual_instrument/DummyOT2Server.sh 
#screen -S VirtualOT2Server ./DummyOT2Server.sh
echo 'Started VirtualOT2Server...'
fi

if [ "$1" == "all" ] | [ "$1" == "sample" ] ; then
screen -d -m -S VirtualSampleServer ~/AFL-automation/server_scripts/virtual_instrument/DummySampleServer.sh
#screen -S VirtualSampleServer ./DummySampleServer.sh 
echo 'Started VirtualSampleServer...'
fi

if [ "$1" == "all" ] | [ "$1" == "scatter" ] ; then
    screen -d -m  -S VirtualSANS ~/AFL-automation/server_scripts/virtual_instrument/VirtualSANS_data.sh
echo 'Started VirtualSANS_data server...'
fi

if [ "$1" == "all" ] | [ "$1" == "spec" ] ; then
	#screen -S VirtualOT2Server ./DummyOT2Server.sh
    screen -d -m  -S VirtualSpec ~/AFL-automation/server_scripts/virtual_instrument/VirtualSpec_data.sh 
	echo 'Started VirtualSpec server...'
fi

if [ "$1" == "help" ] | [ "$1" == "usage" ] | [ -z $1 ] ; then
echo 'Usage: start.sh loader | robot | sample | scatter | spec | all (| help)'
fi

