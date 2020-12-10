#!/bin/bash

ssh piloader2 -f 'screen -d -m  -S LoaderServer /home/pi/NistoRoboto/server_scripts/launchers/OnePumpCetoni.sh '

ssh piot2 -f 'screen -d -m  -S OT2Server /home/pi/NistoRoboto/server_scripts/launchers/OT2Server.sh '

# start sample server here

screen -d -m -S SampleServer /home/nistoroboto/NistoRoboto/server_scripts/launchers/SampleServer.sh 


