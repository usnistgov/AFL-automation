'''

Some notes on how to get this talking:

1) You need the IXXAT usb-can kernel module built and installed (gooooood luuuck, but it works on armv7l)

2) Set up the canbus interface:
	sudo ip link set can0 up type can bitrate 1000000
	sudo ip link set txqueuelen 10 dev can0

3) Put the cetoni qmixsdk c/cython modules on your PYTHONPATH, such that you can import them, see below.


'''




from NistoRoboto.loading.SyringePump import SyringePump

import sys

from qmixsdk import qmixbus
from qmixsdk import qmixpump
from qmixsdk import qmixvalve
from qmixsdk.qmixbus import UnitPrefix, TimeUnit

import time

class CetoniSyringePump(SyringePump):

    def __init__(self,deviceconfig,pumpName="neMESYS_Low_Pressure_1_Pump",existingBus=None,flow_delay=5):
        '''
            Initializes and verifies connection to a Cetoni syringe pump.

            This is quite a bit more complicated/annoying than on a NE1k.

            You have to get the canBUS object, search the bus for pumps, start the bus, then enable the pump drive 

        '''
        self.app = None
        self.name = 'CetoniSyringePump'
        self.flow_delay = flow_delay

        # try to connect
	    if existingBus is not None:
	        print("Opening bus with deviceconfig ", deviceconfig)
	        self.bus = qmixbus.Bus()
	        self.bus.open(deviceconfig, 0)
	    else:
	    	self.bus = existingBus

        print("Looking up devices...")
        self.pump = qmixpump.Pump()
        self.pump.lookup_by_name(pumpname)
        pumpcount = qmixpump.Pump.get_no_of_pumps()
        print("Number of pumps: ", pumpcount)
        for i in range (pumpcount):
            pump2 = qmixpump.Pump()
            pump2.lookup_by_device_index(i)
            print("Name of pump ", i, " is ", pump2.get_device_name())

        assert pumpcount == 1, "Error: this driver does not support >1 pump on a bus.  Probably small hack to fix but it won't work yet."
        

       	# Connect the bus
        self.bus.start()
		
        # Turn on the pump
		print("Enabling pump drive...")
        if self.pump.is_in_fault_state():
            self.pump.clear_fault()
        if not self.pump.is_enabled():
            self.pump.enable(True)
    

        # Calibrate pump


        print("Calibrating pump...")
        self.pump.calibrate()
        time.sleep(0.2)
        calibration_finished = self.wait_calibration_finished(self.pump, 30)
        print("Pump calibrated: ", calibration_finished)

          # reset diameter
        syringe = self.pump.get_syringe_param()
        self.syringe_id_mm = syringe.inner_diameter_mm
        self.piston_stroke_mm = syringe.max_piston_stroke_mm
        self.syringe_volume_ml = syringe.volume_ml #this may not be a real attribute

        self.pump.set_volume_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres)
        self.pump.set_flow_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres, 
            qmixpump.TimeUnit.per_second)

        self.max_rate = self.pump.get_flow_rate_max()
        self.max_volume = self.pump.get_volume_max()


        self.setRate(self.max_rate/2)


        def __del__(self):
	        print("Closing bus...")
	        self.bus.stop()
	        self.bus.close()

    @staticmethod
    def wait_calibration_finished(pump, timeout_seconds):
        """
        The function waits until the given pump has finished calibration or
        until the timeout occurs.
        """
        timer = qmixbus.PollingTimer(timeout_seconds * 1000)
        result = False
        while (result == False) and not timer.is_expired():
            time.sleep(0.1)
            result = pump.is_calibration_finished()
        return result


    @staticmethod
    def wait_dosage_finished(pump, timeout_seconds):
        """
        The function waits until the last dosage command has finished
        until the timeout occurs.
        """
        timer = qmixbus.PollingTimer(timeout_seconds * 1000)
        message_timer = qmixbus.PollingTimer(500)
        result = True
        while (result == True) and not timer.is_expired():
            time.sleep(0.1)
            if message_timer.is_expired():
                print("Fill level: ", pump.get_fill_level())
                message_timer.restart()
            result = pump.is_pumping()
        return not result
        



    def stop(self):
        '''
        Abort the current dispense/withdraw action. 
        '''

        self.pump.stop()

    def withdraw(self,volume,block=True):
        if self.app is not None:
            rate = self.getRate()
            self.app.logger.debug(f'Withdrawing {volume}mL at {rate} mL/min')

   		self.pump.aspirate(volume, self.rate)
        if block:
			self.wait_dosage_finished(self.pump, 30)
            time.sleep(self.flow_delay)
        
    def dispense(self,volume,block=True):
        if self.app is not None:
            rate = self.getRate()
            self.app.logger.debug(f'Dispensing {volume}mL at {rate} mL/min')
        self.pump.dispense(volume, self.rate)
        if block:
			self.wait_dosage_finished(self.pump, 30)
            time.sleep(self.flow_delay)
        


    def setRate(self,rate): #@TODO
        if self.app is not None:
            self.app.logger.debug(f'Setting pump rate to {rate} mL/min')
        self.rate = rate

    def getRate(self): #@TODO
        return self.rate

    def blockUntilStatusStopped(self,pollingdelay=0.2):
        '''
        This is a deprecated function from old serial logic.  It should work, but do not use.  
        '''
        self.wait_dosage_finished(self.pump,30)
        self.wait_calibration_finished(self.pump,30)


    def getStatus(self): #@TODO
        '''
        query the pump status and return a tuple of the status character, 
        infused volume, and withdrawn volume)
        
		This is a deprecated method from old serial logic.  It should work, but do not use.
        '''

        dispensed = self.serial_device.sendCommand('%iDIS\x0D'%self.pumpid)
        # example answer: 10SI0.000W20.00ML
        statuschar = dispensed[3]
        infusedvol = float(dispensed[5:10])
        withdrawnvol = float(dispensed[11:16])

        return(statuschar,infusedvol,withdrawnvol)






