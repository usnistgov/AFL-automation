import numpy as np
import threading
import time
import datetime

class SensorPollingThread(threading.Thread):
    def __init__(self,sensor,period=0.1,callback=None,hv_pipe=None,window=None,noisy=True):
        threading.Thread.__init__(self, name='SignalPollingThread', daemon=True)
        
        self.sensor = sensor
        self.callback = callback
        self.window = window
        self.hv_pipe = hv_pipe
        self.period = period
        self.noisy = noisy
        
        self._stop = False
        self._lock = threading.Lock()
        
        self._signal = []
        
    def read(self):
        with self._lock:
            return self._signal
        
    def terminate(self):
        self._stop = True
        
    def run(self):
        print('Starting runloop for PollingThread')
        i=0
        while not self._stop:
            value = self.sensor.read()
            
                
            with self._lock:
                self._signal.append(value)
                if self.window is not None:
                    self._signal = self._signal[-self.window:]
            
                
            if self.hv_pipe is not None:
                self.hv_pipe.send(np.array([[i,value]]))
            
            if self.callback is not None:
                self.callback(self._signal)
            time.sleep(self.period)
            i+=1
