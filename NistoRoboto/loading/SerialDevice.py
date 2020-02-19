import serial
import time
from NistoRoboto.shared.exceptions import SerialCommsException

class SerialDevice():
    def __init__(self,port,baudrate=19200,timeout=0.5):
        self.serialport = serial.Serial(port,baudrate=baudrate,timeout=timeout)
        self.busy = False
    def sendCommand(self,cmd,response=True,questionmarkOK=False,timeout=-1):
        while self.busy:
            time.sleep(0.1)
        self.busy=True
        self.serialport.write(bytes(cmd,'utf8'))

        if response:
            if timeout is not -1:
                prevtimeout = self.serialport.timeout
                self.serialport.timeout = timeout
            answer = self.serialport.readline().decode("utf-8") 
            if '?' in answer and not questionmarkOK:
                raise SerialCommsException
            if timeout is not -1:
                self.serialport.timeout = prevtimeout
        else:
            answer = None

        self.busy=False
        return answer
