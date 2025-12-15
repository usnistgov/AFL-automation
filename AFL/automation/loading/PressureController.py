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
        self.set_P(dispense_pressure)
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
    def ramp_dispense(self,dispense_start_pressure, dispense_stop_pressure, dispense_time,const_time = 0,block=True):
        '''
        Perform a pressure dispense with a linear ramp in pressure between `dispense_start_pressure` and `dispense_stop_pressure`, stopping after `dispense_time`.  This dispense can be interrupted by calling self.stop().  If const_time is set, the last `const_time` seconds of the dispense will be at constant pressure, with the ramp occurring in the remaining time.
        '''

        self.start_time = time.time()
        self.stop_flag = threading.Event()
        self.active_callback = threading.Thread(target= self._ramp_pressure,args=(dispense_start_pressure,dispense_stop_pressure,dispense_time,const_time,self.stop_flag))
        self.set_P(dispense_start_pressure)
        self.active_callback.start() 

        while not self.active_callback.is_alive():
            time.sleep(0.01)

        if block:
            self.blockUntilStatusStopped()    
        
    def _ramp_pressure(self,dispense_start_pressure,dispense_stop_pressure,dispense_time,const_time,stop_flag):
        pressure_ramp_rate = (dispense_stop_pressure - dispense_start_pressure) / (dispense_time-const_time)
        elapsed_time = time.time() - self.start_time
        while elapsed_time<dispense_time and not stop_flag.is_set():
            elapsed_time = time.time() - self.start_time
            elapsed_time = min(elapsed_time, (dispense_time - const_time))
            self.set_P(dispense_start_pressure + pressure_ramp_rate * elapsed_time)
            time.sleep(0.05)
        self.stop()

    def stop(self):
        '''
        Abort the current timed dispense action.
        '''
        if hasattr(self, 'app') and self.app is not None:
            self.app.logger.info(f'Dispense stop was called, callback status {self.dispenseRunning()}')
        self.set_P(0) 
        try:
            self.active_callback.cancel()   
        except AttributeError: # this is a ramp thread, not a timer
            self.stop_flag.set()
            time.sleep(0.05)
            self.set_P(0)



