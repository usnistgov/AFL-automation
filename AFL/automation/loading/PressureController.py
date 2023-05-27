import threading,time

class PressureController():
    '''
    Abstract superclass for pressure controllers that provides timed dispensing
    '''
    
    def timed_dispense(self,dispense_pressure,dispense_time,block=True):
        '''
        Perform a pressure dispense at pressure `dispense_pressure`, stopping after `dispense_time`.
        This dispense can be interrupted by calling self.stop().
        '''
        
        self.active_callback = threading.Timer(dispense_time,self.stop)
        self.set_P(self.dispense_pressure)
        self.active_callback.start()
        
        while not self.active_callback.is_alive():
            time.sleep(0.01)

        if block:
            self.blockUntilStatusStopped()    
    def blockUntilStatusStopped(self,pollingdelay=0.2):
        '''
        block execution until the controller finishes a dispense
        '''
        if self.active_callback is not None:
            status = self.active_callback.is_alive()
        else:
            status = False
        while status:
            time.sleep(pollingdelay)
            status = self.active_callback.is_alive()
    def dispenseRunning(self):
        ''' 
        Returns true if a timed dispense is running, false otherwise.
        '''
        if self.active_callback is not None:
            return self.active_callback.is_alive()
        else:
            return False
        
    def stop(self):
        '''
        Abort the current timed dispense action.
        '''
        print(f'Dispense stop was called, callback status {self.active_callback.is_alive()}')
        self.set_P(0) 
        self.active_callback.cancel()    
