from AFL.automation.loading.SyringePump import SyringePump
from AFL.automation.loading.SerialDevice import SerialDevice
import time
import threading
import warnings
class PressureControllerAsPump(SyringePump):

    def __init__(self,pressure_controller,dispense_pressure=3.5,implied_flow_rate = 50):
        '''
            Initialize a pressure controller as a syringe pump.

            pressure_controller: controller to connect to
            dispense_pressure: pressure at which dispense should run
            implied_flow_rate: flow rate which should be used to convert to dispense times, mL/min
        '''
        self.app = None
        self.name = 'PressureControllerAsPump'
        self.controller = pressure_controller
        self.dispense_pressure = dispense_pressure
        self.implied_flow_rate = implied_flow_rate
        self.active_callback = None
    def stop(self):
        '''
        Abort the current dispense/withdraw action. Equivalent to pressing stop button on panel.
        '''
        print(f'Pump stop was called, callback status {self.active_callback.is_alive()}')
        self.controller.set_P(0) 
        self.active_callback.cancel()
    def __del__(self):
        self.stop()

    def withdraw(self,volume,block=True,delay=True):
        warnings.warn('dispense only for Pressure controllers at this time')
        #raise NotImplementedError('dispense only for Pressure controllers at this time') 
    def dispense(self,volume,block=True,delay=True):
        if self.app is not None:
            rate = self.getRate()
            self.app.logger.debug(f'Dispensing {volume}mL at {rate} mL/min')
        
        dispense_time = volume / self.implied_flow_rate 
        dispense_time = dispense_time * 60 # convert from min to s as flow rate is in mL/min
        
        
        self.active_callback = threading.Timer(dispense_time,self.stop)
        self.controller.set_P(self.dispense_pressure)
        self.active_callback.start()
        

        if block:
            self.blockUntilStatusStopped()
        
    def setRate(self,rate):
        if self.app is not None:
            self.app.logger.debug(f'Setting pump rate to {rate} mL/min')
        self.implied_flow_rate = rate 
        if self.getRate()!=rate:
            raise ValueError('Pump rate change failed')

    def getRate(self):
        return self.implied_flow_rate

    def emptySyringe(self):
        raise NotImplementedError('this makes no sense for a pressure controller')
    
    def blockUntilStatusStopped(self,pollingdelay=0.2):
        if self.active_callback is not None:
            status = self.active_callback.is_alive()
        while status:
            time.sleep(pollingdelay)
            status = self.active_callback.is_alive()

    def getStatus(self):
        '''
        query the pump status and return a tuple of the status character, 
        infused volume, and withdrawn volume)
        '''

        if self.active_callback.is_alive():
            return ('disp',0,0)
        else:
            return ('S',0,0)




