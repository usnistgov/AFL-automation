import threading
import numpy as np

class Sensor():
    def __init__(self,address=1,channel=0):
        raise NotImplementedError
        
    def calibrate(self):
        raise NotImplementedError
        
    def read(self):
        raise NotImplementedError

class DummySensor1(threading.Thread):
    def __init__(self,period=2,minval=-5,maxval=5):
        threading.Thread.__init__(self, name='DummySensor1', daemon=True)
        self.period = period
        self.minval = minval
        self.maxval = maxval
        
        self._stop = False
        self._lock = threading.Lock()
        self._value = 0
        
    def read(self):
        with self._lock:
            return self._value
    
    def terminate(self):
        self._stop = True
        
    def run(self):
        print('Starting runloop for DummySensor1')
        while not self._stop:
            with self._lock:
                self._value = (self.maxval-self.minval)*np.random.random()+self.minval
                
            time.sleep(self.period)
            
class DummySensor2(threading.Thread):
    def __init__(self,period=0.1,hi_value=5,lo_time=15,hi_time=2):
        threading.Thread.__init__(self, name='DummySensor2', daemon=True)
        self.period = period
        
        self.lo_value = 0
        self.hi_value = hi_value
        self.lo_time = datetime.timedelta(seconds=lo_time)
        self.hi_time = datetime.timedelta(seconds=hi_time)
        self.hi_state = False
        
        self._stop = False
        self._lock = threading.Lock()
        self._value = 0
        
    def driver_status(self):
        if self.hi_state:
            return ['State: IDLE']
        else:
            return ['State: LOAD IN PROGRESS']
        
    def read(self):
        with self._lock:
            return self._value
        
    def terminate(self):
        self._stop = True
        
    def run(self):
        start = datetime.datetime.now()
        print('Starting runloop for DummySensor2')
        while not self._stop:
            
            if ((datetime.datetime.now()-start)<self.lo_time):
                value = np.random.normal(self.lo_value,0.2)
            else:
                self.hi_state = True
                value = np.random.normal(self.hi_value,0.2)
                if ((datetime.datetime.now()-start)>(self.lo_time+self.hi_time)):
                    start = datetime.datetime.now()
                    self.hi_state = False
            
            with self._lock:
                self._value = value
                
            time.sleep(self.period)
