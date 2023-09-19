#!/bin/bash

if [ "$1" == "all" ] || [ "$1" == "loader" ] ; then
screen -ls
fi

if [ "$1" == "all" ] || [ "$1" == "robot" ] ; then
screen -ls
fi

if [ "$1" == "all" ] || [ "$1" == "sample" ] ; then
screen -ls
fi

if [ "$1" == "help" ] || [ "$1" == "usage" ] || [ -z $1 ] ; then
echo 'Usage: status.sh loader | robot | sample | all (| help)'
fi

