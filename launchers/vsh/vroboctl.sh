#!/bin/bash

if [[ "$1" == "stop" ]] || [[ "$1" = "restart" ]] ; then
	if [[ "$2" == "all" ]] || [[ "$2" == "loader" ]] ; then
		screen -X -S VirtualLoaderServer quit
		echo 'Stopped virtual LoaderServer...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "robot" ]] ; then
		screen -X -S VirtualOT2Server quit
		echo 'Stopped virtual OT2Server...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "sample" ]] ; then
		screen -X -S VirtualSampleServer quit
		echo 'Stopped virtual SampleServer...'
	fi
fi

if [[ "$1" == "start" ]] || [[ "$1" = "restart" ]] ; then
	if [[ "$2" == "all" ]] || [[ "$2" == "loader" ]] ; then
        screen -d -m  -S VirtualLoaderServer ~/AFL-automation/server_scripts/virtual_instrument/DummyLoader.sh
	echo 'Started VirtualLoaderServer...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "robot" ]] ; then
		#screen -S VirtualOT2Server ./DummyOT2Server.sh
        screen -d -m  -S VirtualOT2Server ~/AFL-automation/server_scripts/virtual_instrument/DummyOT2Server.sh 
		echo 'Started VirtualOT2Server...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "sample" ]] ; then
		#screen -S VirtualSampleServer ./DummySampleServer.sh 
        screen -d -m  -S VirtualSampleServer ~/AFL-automation/server_scripts/virtual_instrument/DummySampleServer.sh
		echo 'Started VirtualSampleServer...'
	fi
fi

if [[ "$1" == "status" ]] ; then
	if [[ "$2" == "all" ]] || [[ "$2" == "loader" ]] ; then
		screen -ls
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "robot" ]] ; then
		screen -ls
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "sample" ]] ; then
		screen -ls
	fi
fi

if [[ "$1" == "help" ]] || [[ "$1" == "usage" ]] || [[ -z $1 ]] ; then
	echo 'Usage: vroboctl.sh (start || stop || status || restart) (loader || robot || sample || all)'
fi

