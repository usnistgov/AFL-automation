#!/bin/bash

if [ "$1" == "all" ] | [ "$1" == "loader" ] ; then
ssh piloader2 -f 'screen -X -S LoaderServer quit'
echo 'Stopped LoaderServer...'
fi

if [ "$1" == "all" ] | [ "$1" == "robot" ] ; then
ssh piot2 -f 'screen -X -S OT2Server quit'
echo 'Stopped OT2Server...'
fi

if [ "$1" == "all" ] | [ "$1" == "sample" ] ; then
screen -X -S SampleServer quit
echo 'Stopped SampleServer...'
fi


if [ "$1" == "help" ] | [ "$1" == "usage" ] | [ -z $1 ] ; then
echo 'Usage: stop.sh loader | robot | sample | all (| help)'
fi

