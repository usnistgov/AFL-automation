import lazy_loader as lazy
GPIO = lazy.load("RPi.GPIO", require="AFL-automation[rpi-gpio]")

class PiGPIO():
	def __init__(self,channels,mode='BCM',pull_dir='UP'):
		'''
		Initializes GPIO pins in channels and maps their values to a local dict.

		Params:
		channels (dict):
			mapping of pin id to load name, e.g. {0:'arm_up',1:'arm_down'}
		mode (str, 'BCM' or 'BOARD', default BCM):
			pin numbering scheme to use
		pull_dir (str or dict, default 'up')
			if string, 'UP' or 'DOWN' direction to pull all pins
			if dict, key = pin number, val = 'UP' or 'DOWN'

		'''
		self.channels = {int(key):val for key,val in channels.items()}

		self.state = {}
		if mode == 'BCM':
			GPIO.setmode(GPIO.BCM)
		elif mode == 'BOARD':
			GPIO.setmode(GPIO.BOARD)
		else:
			raise ValueError('invalid mode in GPIORelay')

		if type(pull_dir) != dict:
			if pull_dir == 'UP':
				pull_dir = {key:'UP' for key,val in self.channels.items()}
			elif pull_dir == 'DOWN':
				pull_dir = {key:'DOWN' for key,val in self.channels.items()}
			else:
				raise ValueError('invalid pull_dir in GPIORelay')
		#Setup pins:

		for key,val in self.channels.items():
			if pull_dir[key] == 'UP':
				GPIO.setup(key,GPIO.IN,pull_up_down=GPIO.PUD_UP)
			elif pull_dir[key] == 'DOWN':
				GPIO.setup(key,GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
			else:
				raise ValueError('invalid pull_dir in GPIORelay')
			GPIO.add_event_detect(key,GPIO.BOTH,callback=self.eventcb)#,bouncetime=200)



		self.ids = {val:key for key,val in self.channels.items()}

		#do an initial read of all the pin state and create self.state which maps name to val
		for key,val in self.channels.items():
			self.state[val] = GPIO.input(key)
	def eventcb(self,channel):
		'''
		In response to an edge detect, read a channel and update the local state dict.

		'''
		self.state[self.channels[channel]] = GPIO.input(channel)

