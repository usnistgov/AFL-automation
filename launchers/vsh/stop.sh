#!/bin/bash

if [ "$1" == "all" ] | [ "$1" == "loader" ] ; then
#screen -X -S VirtualLoaderServer quit
screen -S VirtualLoaderServer -X quit
echo 'Stopped VirtualLoaderServer...'
fi

if [ "$1" == "all" ] | [ "$1" == "robot" ] ; then
#screen -X -S VirtualOT2Server quit
screen -S VirtualOT2Server -X quit
echo 'Stopped VirtualOT2Server...'
fi

if [ "$1" == "all" ] | [ "$1" == "sample" ] ; then
#screen -X -S VirtualSampleServer quit
screen -S VirtualSampleServer -X quit
echo 'Stopped VirtualSampleServer...'
fi

if [ "$2" == "all" ] | [ "$2" == "scatter" ] ; then
	#screen -X -S VirtualLoaderServer quit
	screen -S VirtualSANS -X quit
	echo 'Stopped VirtualSANS server...'
fi

if [ "$2" == "all" ] | [ "$2" == "spec" ] ; then
	#screen -X -S VirtualOT2Server quit
	screen -S VirtualSpec -X quit
	echo 'Stopped VirtualSpec server...'
fi

if [ "$1" == "help" ] | [ "$1" == "usage" ] | [ -z $1 ] ; then
echo 'Usage: stop.sh loader | robot | sample | scatter | spec | all (| help)'
fi

