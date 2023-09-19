#!/bin/bash

if [ "$1" == "all" ] | [ "$1" == "loader" ] ; then
screen -X -S VirtualLoaderServer quit
echo 'Stopped VirtualLoaderServer...'
fi

if [ "$1" == "all" ] | [ "$1" == "robot" ] ; then
screen -X -S VirtualOT2Server quit
echo 'Stopped VirtualOT2Server...'
fi

if [ "$1" == "all" ] | [ "$1" == "sample" ] ; then
screen -X -S VirtualSampleServer quit
echo 'Stopped VirtualSampleServer...'
fi


if [ "$1" == "help" ] | [ "$1" == "usage" ] | [ -z $1 ] ; then
echo 'Usage: stop.sh loader | robot | sample | all (| help)'
fi

