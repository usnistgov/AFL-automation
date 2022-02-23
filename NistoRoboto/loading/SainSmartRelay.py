from NistoRoboto.loading.MultiChannelRelay import MultiChannelRelay
from NistoRoboto.loading.SerialDevice import SerialDevice
import atexit

class SainSmartRelay(MultiChannelRelay,SerialDevice):
	def __init__(self,relaylabels,serial_port,timeout=0.5):
		'''
		Init connection to a SainSmart 16-channel USB relay module.

		Params:
		relaylabels (dict):
			mapping of port id to load name, e.g. {0:'arm_up',1:'arm_down'}
		serial_port (str):
			port to connect to
		'''
		#Sanitize labels:

		for port_id in range(1,16):
			if port_id not in relaylabels.keys():
				relaylabels[port_id] = f'UNUSED{port_id}'

		self.labels = relaylabels

		self.ids = {val:key for key,val in self.labels.items()}


		SerialDevice.__init__(self,port=serial_port,timeout=timeout,baudrate=9600,raw_writes=True)
		self.serialport.write(usbrelay[17][0])
		self.portvals = [False]*17
		atexit.register(self.setAllChannelsOff)

	
	def setAllChannelsOff(self):
		self.serialport.write(usbrelay[17][0])

	def setChannels(self,channels):
			'''
			Write a value (True, False) to the channels specified in channels

			Parameters:
			channels (dict):
				dict of channels, keys as either str (name) or int (id) to write to, vals as the value to write


			'''
			remapped_channels = {}
			for key,val in channels.items():
				if type(key)==str:
					remapped_channels[self.ids[key]]=val
				else:
					remapped_channels[key]=val

			for key,val in remapped_channels.items():
				self.serialport.write(usbrelay[key][val])
				self.portvals[key] = val
	def getChannels(self,asid=False):
		'''
		Read the current state of all channels

		Parameters:
		asid (bool,default false):
		Dict keys should simply be the id, not the name.

		Returns:
		(dict) key:value mappings of state.
		'''

		retval = {}
		for portid,name in self.labels.items():
			if asid:
				retval[portid] = self.portvals[portid]
			else:
				retval[name] = self.portvals[portid]
		return retval

	def toggleChannels(self,channels):
		cmd = {}
		for port in channels:
			if type(port)==str:
				cmd[self.ids[port]] = not self.portvals[self.ids[port]]

			else:
				cmd[port] = not self.portvals[port]
		self.setChannels(cmd)

					
usbrelay = [[b':FE0100200000FF\r\n', b':FE0100000010F1\r\n'],   # status & status return
            [b':FE0500000000FD\r\n', b':FE050000FF00FE\r\n'],   # channel-1
            [b':FE0500010000FC\r\n', b':FE050001FF00FD\r\n'],   # channel-2
            [b':FE0500020000FB\r\n', b':FE050002FF00FC\r\n'],   # channel-3
            [b':FE0500030000FA\r\n', b':FE050003FF00FB\r\n'],   # channel-4
            [b':FE0500040000F9\r\n', b':FE050004FF00FA\r\n'],   # channel-5
            [b':FE0500050000F8\r\n', b':FE050005FF00F9\r\n'],   # channel-6
            [b':FE0500060000F7\r\n', b':FE050006FF00F8\r\n'],   # channel-7
            [b':FE0500070000F6\r\n', b':FE050007FF00F7\r\n'],   # channel-8
            [b':FE0500080000F5\r\n', b':FE050008FF00F6\r\n'],   # channel-9
            [b':FE0500090000F4\r\n', b':FE050009FF00F5\r\n'],   # channel-10
            [b':FE05000A0000F3\r\n', b':FE05000AFF00F4\r\n'],   # channel-11
            [b':FE05000B0000F2\r\n', b':FE05000BFF00F3\r\n'],   # channel-12
            [b':FE05000C0000F1\r\n', b':FE05000CFF00F2\r\n'],   # channel-13
            [b':FE05000D0000F0\r\n', b':FE05000DFF00F1\r\n'],   # channel-14
            [b':FE05000E0000FF\r\n', b':FE05000EFF00F0\r\n'],   # channel-15
            [b':FE05000F0000FE\r\n', b':FE05000FFF00FF\r\n'],   # channel-16
            [b':FE0F00000010020000E1\r\n', b':FE0F0000001002FFFFE3\r\n']]   # all channels


'''

"""
Sainsmart 16-Channel 9-36v USB Relay Module (CH341 chip)(sku# 101-70-208)
1. Requires CH341 Windows driver installed (see http://wiki.sainsmart.com/index.php/101-70-208)
2. The hex table provided by Sainsmart requires converting to ASCII chars (see 'usbrelay' below)
3. Format of 'usbrelay' two-dimensional array is:
        usbrelay = [row][ch-off, ch-on] so that the 2nd index selects ON/OFF value  
                                                                  while the 1st index selects the array row.  
        Example...
            status    = usbrelay[0][1]      # row-0  (status)
            stat_ret  = usbrelay[0][0]      # row-0  (status return)
            ch_1_on   = usbrelay[1][1]      # row-1  (chan-1 off)
            ch_1_off  = usbrelay[1][0]      # row-1  (chan-1 off)
            ch_16_on  = usbrelay[16][1]     # row-16 (chan-16 on)
            ch_16_off = usbrelay[16][0]     # row-16 (chan-16 off)
            all_on    = usbrelay[17][1]     # row-17 (all on)
            all_off   = usbrelay[17][0]     # row-17 (all off)
"""

'''


