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
import datetime
class CetoniSyringePump(SyringePump):

    def __init__(self,deviceconfig,configdir='/home/pi/QmixSDK_Raspi/config/',lookupByName=False,pumpName=None,existingBus=None,syringeName=None,flow_delay=5):
        '''
            Initializes and verifies connection to a Cetoni syringe pump.

            This is quite a bit more complicated/annoying than on a NE1k.

            You have to get the canBUS object, search the bus for pumps, start the bus, then enable the pump drive 

        '''

        self.app = None
        self.name = 'CetoniSyringePump'
        self.flow_delay = flow_delay

        deviceconfig = configdir + deviceconfig + '/'
        # try to connect
        if existingBus is None:
            print(f"Opening bus with deviceconfig {deviceconfig}")
            self.bus = qmixbus.Bus()
            self.bus.open(deviceconfig, 0)
        else:
            self.bus = existingBus

        print("Looking up devices...")
        if lookupByName:
            self.pump = qmixpump.Pump()
            self.pump.lookup_by_name(pumpName)
        else:
            pumpcount = qmixpump.Pump.get_no_of_pumps()
            print("Number of pumps: ", pumpcount)
            #assert pumpcount == 1, "Error: this driver does not support >1 pump on a bus.  Probably small hack to fix but it won't work yet."
            self.pump = qmixpump.Pump()
            self.pump.lookup_by_device_index(0)
            print("Name of pump is ", self.pump.get_device_name())

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

        if syringeName is not None:
            print('Syringe Parameter Lookup Not Yet Supported')

        syringe = self.pump.get_syringe_param()
        self.syringe_id_mm = syringe.inner_diameter_mm
        self.piston_stroke_mm = syringe.max_piston_stroke_mm

        self.pump.set_volume_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres)
        self.pump.set_flow_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres, 
            qmixpump.TimeUnit.per_minute)


        self.syringe_volume_ml = self.pump.get_volume_max() #this may not be a real attribute

        
        self.max_rate = self.pump.get_flow_rate_max()
        self.max_volume = self.pump.get_volume_max()

        print(f'Currently loaded syringe is a {self.syringe_volume_ml}, max pump rate {self.max_rate}, ID {self.syringe_id_mm}, stroke {self.piston_stroke_mm}')

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
        start = datetime.datetime.now()
        while (result == True) and not timer.is_expired():
            time.sleep(0.1)
            if message_timer.is_expired():
                print("Fill level: ", pump.get_fill_level())
                message_timer.restart()
            result = pump.is_pumping()
            #print(f'Polling loop status: pump reports is_pumping() = {result}, timeout timer is_expired() = {timer.is_expired()}, it has been {datetime.datetime.now()-start} since start by snek-watch and expiration should be {timeout_seconds}')
            
        return not result
        



    def stop(self):
        '''
        Abort the current dispense/withdraw action. 
        '''

        self.pump.stop()

    def withdraw(self,volume,block=True,delay=True):
        rate = self.getRate()
        expected_duration = volume / rate * 60 # anticipated duration of pump move in s

        timeout = expected_duration + 30

        timeout = max((timeout),30) # in case things get really weird.
        if self.app is not None:
            self.app.logger.debug(f'Withdrawing {volume}mL at {rate} mL/min, expected to take {expected_duration} s')

        if (self.getLevel()+volume) > self.max_volume:
            self.app.logger.warn(f'Requested withdrawal of {volume} but current level is {self.getLevel()} of a max {self.max_volume}.  Moving to {self.max_volume}')
            self.setLevel(self.max_volume)

        self.pump.aspirate(float(volume), self.rate)
        if block:
            self.wait_dosage_finished(self.pump, timeout)
        if delay:
            time.sleep(self.flow_delay)
        
    def dispense(self,volume,block=True,delay=True):
        rate = self.getRate()
        expected_duration = volume / rate * 60 # anticipated duration of pump move in s

        timeout = expected_duration + 30

        timeout = max((timeout),30) # in case things get really weird.

        if self.app is not None:
            self.app.logger.debug(f'Dispensing {volume}mL at {rate} mL/min, expected to take {expected_duration} s')
        if (self.getLevel() - volume) < 0:
            self.app.logger.warn(f'Requested dispense of {volume} but current level is {self.getLevel()} .  Moving to 0')
            self.setLevel(0)



        self.pump.dispense(float(volume), self.rate)
        if block:
            self.wait_dosage_finished(self.pump, timeout)
        if delay:
            time.sleep(self.flow_delay)
        


    def setRate(self,rate): #@TODO
        if self.app is not None:
            self.app.logger.debug(f'Setting pump rate to {rate} mL/min')
        self.rate = float(rate)

    def getRate(self): #@TODO
        return self.rate

    def emptySyringe(self):
        self.setLevel(0)

    def getLevel(self):
        return self.pump.get_fill_level()
        #self.assertAlmostEqual(max_volume, fill_level_is)

    def setLevel(self,level):
        self.pump.set_fill_level(level, self.rate)

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






