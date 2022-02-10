import piplates.RELAYplate as RELAYplate
from NistoRoboto.loading.MultiChannelRelay import MultiChannelRelay

class PiPlatesRelay(MultiChannelRelay):

	def __init__(self,relaylabels,board_id=0):
		'''
		Init connection to a labeled Pi-Plates Relay module.

		Params:
		relaylabels (dict):
			mapping of port id to load name, e.g. {0:'arm_up',1:'arm_down'}
		board_id (int, default 0):
			board ID to connect to, set via jumpers on the board.
		'''
		conn = RELAYplate.getID(board_id)
		print(f'Got connection response from board: {conn}')
		RELAYplate.RESET(board_id)
		self.board_id = board_id

		#Sanitize labels:

		for port_id in range(1,7):
			if port_id not in relaylabels.keys():
				relaylabels[port_id] = f'UNUSED{port_id}'

		self.labels = relaylabels

		self.ids = {val:key for key,val in self.labels.items()}

	def setChannels(self,channels):
		'''
		Write a value (True, False) to the channels specified in channels

		Parameters:
		channels (dict):
			dict of channels, keys as either str (name) or int (id) to write to, vals as the value to write


		'''

		for key,val in channels.items():
			if type(key)==str:
				channels[self.ids[key]]=val
				del channels[key]

		for key,val in channels.items():
			if val==True:
				RELAYplate.relayON(self.board_id,key)
			elif val==False:
				RELAYplate.relayOFF(self.board_id,key)
			else:
				raise KeyError('Improper value for relay set.')


		'''

		relayALL(addr,value) – 
		used to control the state of all relays with a single command. 
		“value” is a 7 bit number with each bit corresponding to a relay. 
		Bit 0 is relay 1, bit 1 is relay 2, and so on. 
		To turn all the relays on at once, use the number 127 for the value.
		relaySTATE(addr) – 
		Returns a 7-bit number with the current state of each relay. 
		Bit 0 is relay 1, bit 1 is relay 2, and so on. 
		A “1” in a bit position means that the relay is on and zero means that it’s off.
		'''

	def getChannels(self,asid=False):
		'''
		Read the current state of all channels

		Parameters:
		asid (bool,default false):
		Dict keys should simply be the id, not the name.

		Returns:
		(dict) key:value mappings of state.
		'''
		allchannels = RELAYplate.relaySTATE(self.board_id)

		retval = {}
		for portid,name in self.labels.items():
			if asid:
				retval[portid] = bool(allchannels & 2**portid)
			else:
				retval[name] = bool(allchannels & 2**portid)
		return retval


	def toggleChannels(self,channels):
		ids = []
		for port in channels:
			if type(port)==str:
				ids.append(self.ids[port])
			else:
				ids.append(port)

		for port in ids:	
			RELAYplate.relayTOGGLE(self.board_id,port)

	
