import numpy as np
import threading
import time
import datetime

class SensorPollingThread(threading.Thread):
    def __init__(self,sensor,period=0.1,callback=None,hv_pipe=None,window=None,filename=None,daemon=True):
        threading.Thread.__init__(self, name='SignalPollingThread', daemon=daemon)
        
        self.sensor = sensor
        self.callback = callback
        self.window = window
        self.hv_pipe = hv_pipe
        self.period = period
        self.filename = filename
        
        self._stop = False
        self._lock = threading.Lock()
        
        self._buffer_rolling_start = None
        self._buffer_rolling = []

        self._buffer_load = []
        self._buffer_load_timeout = datetime.timedelta(seconds=180)
        self._buffer_load_start = None
        
    def read(self):
        with self._lock:
            return self._buffer_rolling

    def read_load_buffer(self):
        with self._lock:
            return self._buffer_load

    def reset_load_buffer(self):
        with self._lock:
            self._buffer_load = []
            self._buffer_load_start = datetime.datetime.now()
        
    def terminate(self):
        self._stop = True

    def alive(self):
        return self._stop
        
    def run(self):
        i=0
        self._buffer_rolling_start = datetime.datetime.now()
        print(f'Starting runloop for PollingThread:')
        while not self._stop:
            value = self.sensor.read()

            
            with self._lock:
                now = datetime.datetime.now()
                self._buffer_rolling.append([now.timestamp(),value])
                if self.window is not None:
                    self._buffer_rolling = self._buffer_rolling[-self.window:]

                if (self._buffer_load_start is not None):
                    buffer_dt = now-self._buffer_load_start
                    if (buffer_dt<self._buffer_load_timeout):
                        self._buffer_load.append([buffer_dt.total_seconds(),value])
            
                
            if self.hv_pipe is not None:
                self.hv_pipe.send(np.array([[i,value]]))

            if self.filename is not None:
                datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y%m%d-%H:%M:%S-%fus')
                with open(filename,'a') as f:
                    f.write(f'{datestr},{i},{value}\n')
            
            if self.callback is not None:
                self.callback(self._buffer_rolling)
            time.sleep(self.period)
            i+=1
