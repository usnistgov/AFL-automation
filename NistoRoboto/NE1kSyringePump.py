class NE1kSyringePump(SyringePump,SerialDevice):

	def __init__(self,port,syringe_id_mm,syringe_volume,baud=9600,daisy_chain=None,id=None):
		if daisy_chain is not None:
			self.serialport = daisy_chain.serialport
			self.id = id
		else:
			self.serialport = serial.Serial(port=port,baudrate=baud,timeout=0.5)

		# try to connect

		if self.id is None:
			for i in range(10):
       			if len(self.sendCommand('%iADR\x0D'%i))>0:
            		self.id = i
            		break
        else:
        	if len(self.sendCommand('%iADR\x0D'%i))==0:
        		raise NoDeviceFoundException

      	# reset diameter
        self.syringe_id_mm = syringe_id_mm
        self.syringe_volume = syringe_volume

    	self.stop()#stop the pump
    	self.sendCommand('%iDIA %f\x0D'%(self.id,syringe_id_mm)) #set the diameter
    	readback = self.sendCommand('%iDIA\x0D'%self.id) #readback
    
        #@TODO: parse readback and verify set succeded

    def stop(self):
        self.sendCommand('%iSTP\x0D'%self.id) 

    def withdraw(self,volume,block=True):
        self.sendCommand('%iVOL ML\x0D'%self.id)
        self.sendCommand('%iVOL %f\x0D'%(self.id,volume))
        self.sendCommand('%iDIR WDR\x0D'%self.id)
        self.sendCommand('%iRUN\x0D',response=block)

    def dispense(self,volume,block=True):
        self.sendCommand('%iVOL ML\x0D'%self.id)
        self.sendCommand('%iVOL %f\x0D'%(self.id,volume))
        self.sendCommand('%iDIR INF\x0D'%self.id)
        self.sendCommand('%iRUN\x0D',response=block)
        
    def setRate(self,rate):
        self.sendCommand('%iRAT%fMH\x0D'%(self.id,rate))

    def getRate(self,rate):
        output = self.sendCommand('%iRAT\x0D'%self.id)
        units = output[-3:-1]
        if units=='MH':
            rate = float(output[4:-3])*1000
        if units=='UH':
            rate = float(output[4:-3])/1000
        return rate


