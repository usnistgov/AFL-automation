from AFL.automation.loading.SyringePump import SyringePump
from AFL.automation.loading.SerialDevice import SerialDevice
import time

class DummyPump(SyringePump):

    def __init__(self):
        '''
            Dummy pump for testing - does nothing, but boy does it look good doing it.

        '''
        self.app = None
        self.name = 'DummyPump'
        self.flow_delay = 1
        self.rate = 30
       
    def stop(self):
        '''
        Abort the current dispense/withdraw action. Equivalent to pressing stop button on panel.
        '''
        print('Pump Stopping')
    def withdraw(self,volume,block=True,delay=True):
        print(f'Withdrawing {volume}')
        time.sleep(volume/self.rate*60)
        if delay:
            time.sleep(self.flow_delay)
        
    def dispense(self,volume,block=True,delay=True):
        if self.app is not None:
            rate = self.getRate()
            self.app.logger.debug(f'Dispensing {volume}mL at {rate} mL/min')
        print(f'Dispensing {volume}')
        time.sleep(volume/self.rate*60)
        if delay:
            time.sleep(self.flow_delay)
        
    def setRate(self,rate):
        if self.app is not None:
            self.app.logger.debug(f'Setting pump rate to {rate} mL/min')
        self.rate = rate

    def getRate(self):
        return self.rate

    def emptySyringe(self):
        self.dispense(self.syringe_volume*0.9)

    def blockUntilStatusStopped(self,pollingdelay=0.2):
        pass
    def getStatus(self):
        '''
        query the pump status and return a tuple of the status character, 
        infused volume, and withdrawn volume)
        '''
        return(1,1,1)






