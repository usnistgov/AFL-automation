#!/bin/bash

if [ "$1" == "stop" ] || [ "$1" = "restart"] ; then
	if [ "$2" == "all" ] || [ "$2" == "loader" ] ; then
		ssh piloader2 -f 'screen -X -S LoaderServer quit'
		echo 'Stopped LoaderServer...'
	fi

	if [ "$2" == "all" ] || [ "$2" == "robot" ] ; then
		ssh piot2 -f 'screen -X -S OT2Server quit'
		echo 'Stopped OT2Server...'
	fi

	if [ "$2" == "all" ] || [ "$2" == "sample" ] ; then
		screen -X -S SampleServer quit
		echo 'Stopped SampleServer...'
	fi
fi

if [ "$1" == "start" ] || [ "$1" = "restart"] ; then
	if [ "$2" == "all" ] | [ "$2" == "loader" ] ; then
		ssh piloader2 -f 'screen -d -m  -S LoaderServer /home/pi/NistoRoboto/server_scripts/launchers/OnePumpCetoni.sh '
		echo 'Started LoaderServer...'
	fi

	if [ "$2" == "all" ] | [ "$2" == "robot" ] ; then
		ssh piot2 -f 'screen -d -m  -S OT2Server /root/user_storage/server_scripts/launchers/OT2Server.sh '
		echo 'Started OT2Server...'
	fi

	if [ "$2" == "all" ] | [ "$2" == "sample" ] ; then
		screen -d -m -S SampleServer /home/nistoroboto/nistoroboto/server_scripts/launchers/SampleServer.sh 
		echo 'Started SampleServer...'
	fi
fi

if [ "$1" == "status" ] ; then
	if [ "$2" == "all" ] || [ "$2" == "loader" ] ; then
		ssh piloader2 -f 'screen -ls'
	fi

	if [ "$2" == "all" ] || [ "$2" == "robot" ] ; then
		ssh piot2 -f 'screen -ls'
	fi

	if [ "$2" == "all" ] || [ "$2" == "sample" ] ; then
		screen -ls
	fi

if [ "$1" == "help" ] | [ "$1" == "usage" ] | [ -z $1 ] ; then
	echo 'Usage: roboctl.sh (start | stop | status | restart) (loader | robot | sample | all)'
fi

