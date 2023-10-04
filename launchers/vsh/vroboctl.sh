#!/bin/bash

if [[ "$1" == "stop" ]] || [[ "$1" = "restart" ]] ; then
	if [[ "$2" == "all" ]] || [[ "$2" == "loader" ]] ; then
		#screen -X -S VirtualLoaderServer quit
		screen -S VirtualLoaderServer -X quit
		echo 'Stopped virtual LoaderServer...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "robot" ]] ; then
		#screen -X -S VirtualOT2Server quit
		screen -S VirtualOT2Server -X quit
		echo 'Stopped virtual OT2Server...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "sample" ]] ; then
		#screen -X -S VirtualSampleServer quit
		screen -S VirtualSampleServer -X quit
		echo 'Stopped virtual SampleServer...'
	fi
	
    if [[ "$2" == "all" ]] || [[ "$2" == "scatter" ]] ; then
		#screen -X -S VirtualLoaderServer quit
		screen -S VirtualSANS -X quit
		echo 'Stopped VirtualSANS server...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "spec" ]] ; then
		#screen -X -S VirtualOT2Server quit
		screen -S VirtualSpec -X quit
		echo 'Stopped VirtualSpec server...'
	fi
fi

if [[ "$1" == "start" ]] || [[ "$1" = "restart" ]] ; then
	if [[ "$2" == "all" ]] || [[ "$2" == "loader" ]] ; then
        screen -d  -S VirtualLoaderServer ~/AFL-automation/server_scripts/virtual_instrument/DummyLoader.sh
	echo 'Started VirtualLoaderServer...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "robot" ]] ; then
		#screen -S VirtualOT2Server ./DummyOT2Server.sh
        screen -d  -S VirtualOT2Server ~/AFL-automation/server_scripts/virtual_instrument/DummyOT2Server.sh 
		echo 'Started VirtualOT2Server...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "sample" ]] ; then
		#screen -S VirtualSampleServer ./DummySampleServer.sh 
        screen -d  -S VirtualSampleServer ~/AFL-automation/server_scripts/virtual_instrument/DummySampleServer.sh
		echo 'Started VirtualSampleServer...'
	fi
	
    if [[ "$2" == "all" ]] || [[ "$2" == "scatter" ]] ; then
        screen -d  -S VirtualSANS ~/AFL-automation/server_scripts/virtual_instrument/VirtualSANS_data.sh
	echo 'Started VirtualSANS_data server...'
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "spec" ]] ; then
		#screen -S VirtualOT2Server ./DummyOT2Server.sh
        screen -d  -S VirtualSpec ~/AFL-automation/server_scripts/virtual_instrument/VirtualSpec_data.sh 
		echo 'Started VirtualSpec server...'
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
	
    if [[ "$2" == "all" ]] || [[ "$2" == "scatter" ]] ; then
		screen -ls
	fi

	if [[ "$2" == "all" ]] || [[ "$2" == "spec" ]] ; then
		screen -ls
	fi
fi

if [[ "$1" == "help" ]] || [[ "$1" == "usage" ]] || [[ -z $1 ]] ; then
	echo 'Usage: vroboctl.sh (start || stop || status || restart) (loader || robot || sample || scatter || spec || all)'
fi

