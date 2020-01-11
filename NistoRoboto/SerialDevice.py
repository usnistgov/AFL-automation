import serial

class SerialDevice():

    def sendCommand(self,cmd,response=True,questionmarkOK=False):
        self.serialport.write(bytes(cmd,'utf8'))
        if response:
            answer = self.serialport.readline().decode("utf-8") 
            if '?' in answer and not questionmarkOK:
                raise SerialCommsException
            return answer