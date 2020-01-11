import serial

class SerialDevice():

	def sendCommand(self,cmd,response=True):
        self.serialport.write(cmd)
        if response:
            answer = self.serialport.readline()
            if '?' in answer:
                raise SerialCommsException
            return answer