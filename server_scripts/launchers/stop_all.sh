#!/bin/bash

ssh piloader2 -f 'screen -X -S LoaderServer quit'

ssh piot2 -f 'screen -X -S OT2Server quit'

# start sample server here

screen -X -S SampleServer quit


