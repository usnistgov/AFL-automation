from SyringePump import *
from SerialDevice import *
import serial

class NE1kSyringePump(SyringePump,SerialDevice):

    def __init__(self,port,syringe_id_mm,syringe_volume,baud=9600,daisy_chain=None,pumpid=None):
        self.pumpid = pumpid
        if daisy_chain is not None:
            self.serialport = daisy_chain.serialport
        else:
            self.serialport = serial.Serial(port=port,baudrate=baud,timeout=0.5)

        # try to connect

        if self.pumpid is None:
            for i in range(10):
                   if len(self.sendCommand('%iADR\x0D'%i))>0:
                    self.pumpid = i
                    break
        else:
            if len(self.sendCommand('%iADR\x0D'%self.pumpid))==0:
                raise NoDeviceFoundException


        assert self.pumpid is not None, "Error: no answer from any of the first 10 pumps.  Is speed correct?"
          # reset diameter
        self.syringe_id_mm = syringe_id_mm
        self.syringe_volume = syringe_volume

        self.stop()#stop the pump
        self.sendCommand('%iDIA %.02f\x0D'%(self.pumpid,syringe_id_mm)) #set the diameter
        readback = self.sendCommand('%iDIA\x0D'%self.pumpid) #readback
        dia = float(readback[4:-1])
        assert dia==syringe_id_mm, "Warning: syringe diameter set failed.  Commanded diameter "+str(syringe_id_mm)+", read back "+str(dia)

    def stop(self):
        self.sendCommand('%iSTP\x0D'%self.pumpid,questionmarkOK=True) 

    def withdraw(self,volume,block=True):
        self.sendCommand('%iVOLML\x0D'%self.pumpid)
        self.sendCommand('%iVOL %.03f\x0D'%(self.pumpid,volume))
        self.sendCommand('%iDIRWDR\x0D'%self.pumpid)
        self.sendCommand('%iRUN\x0D'%self.pumpid,response=block)
        #@TODO: the response is not blocking.  Poll pump status to check when move complete, or set a longer pyserial timeout

    def dispense(self,volume,block=True):
        self.sendCommand('%iVOLML\x0D'%self.pumpid)
        self.sendCommand('%iVOL%.03f\x0D'%(self.pumpid,volume))
        self.sendCommand('%iDIRINF\x0D'%self.pumpid)
        self.sendCommand('%iRUN\x0D'%self.pumpid,response=block)
        
    def setRate(self,rate):
        self.sendCommand('%iRAT%.03fMM\x0D'%(self.pumpid,rate))

    def getRate(self,rate):
        output = self.sendCommand('%iRAT\x0D'%self.pumpid)
        units = output[-3:-1]
        if units=='MM':
            rate = float(output[4:-3])
        elif units=='UM':
            rate = float(output[4:-3])/1000
        elif units=='MH':
            rate = float(output[4:-3])/60
        elif units=='UH':
            rate = float(output[4:-3])/60/1000
        return rate


