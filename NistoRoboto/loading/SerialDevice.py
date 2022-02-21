import serial
import time
from NistoRoboto.shared.exceptions import SerialCommsException

class SerialDevice():
    def __init__(self,port,baudrate=19200,timeout=0.5,raw_writes=False):
        self.serialport = serial.Serial(port,baudrate=baudrate,timeout=timeout)
        self.busy = False
        self.raw_writes = raw_writes
    def sendCommand(self,cmd,response=True,questionmarkOK=False,timeout=-1,debug=False):
        while self.busy:
            #if debug:
            #    print('awaiting port not busy...')
            time.sleep(0.1)
        self.busy=True
        #print('passed busy check, performing write')
        #print(self.serialport)
        if self.raw_writes:
            self.serialport.write(cmd)
        else:
            self.serialport.write(bytes(cmd,'utf8'))
        #if debug:
        #    print(f'wrote {cmd} to port...')
        if response:
            #if debug:
            #    print(f'awaiting response...')
            if timeout is not -1:
                prevtimeout = self.serialport.timeout
                self.serialport.timeout = timeout
            answer = self.serialport.readline().decode("utf-8") 
            print(cmd)
            print(f'To device: {cmd}, answer was {answer}')
            if '?' in answer and not questionmarkOK:
                raise SerialCommsException
            if timeout is not -1:
                self.serialport.timeout = prevtimeout
        else:
            answer = None

        self.busy=False
        return answer
