from FlowSelector import *
from SerialDevice import *
import serial

class ViciMultiposSelector(FlowSelector,SerialDevice):
	def __init__(self,port,baud=9600,portlabels=None):
		'''
		connect to valve and query the number of positions

		parameters:
			port - string describing the serial port the actuator is connected to
			baud - baudrate to use
			portlabels - dict for smart port naming, of the form {'sample':3,'instrument':4,'rinse':5,'waste':6}
		'''
		self.serialport = serial.Serial(port=port,baudrate=baud,timeout=0.5)
		self.npositions = int(self.sendCommand('NP\x0D')[2:4])

		self.portlabels = portlabels



	def selectPort(self,port,direction=None):
		'''
			moves the selector to portnum

			if direction is set to either "CW" or "CCW" it moves the actuator in that direction.  
			if unset or other value, will move via most efficient route.

		'''

		if type(port) is str:
			portnum = self.portlabels[port]
		else:
			portnum = int(port)

		assert portnum <= self.npositions, "That port doesn't exist."

		if direction=="CCW":
			readback = self.sendCommand('CC%02i\x0D'%portnum,response=False)
		else if direction== "CW":
			readback = self.sendCommand('CW%02i\x0D'%portnum,response=False)
		else:
			readback = self.sendCommand('GO%02i\x0D'%portnum,response=False)

	def getPort(self,as_str):
		'''
			query the current selected position
		'''
		portnum = int(self.sendCommand('CP\x0D')[2:4])
