import numpy as np
import threading
import time
import datetime

from piplates import DAQC2plate

import RPi.GPIO as GPIO 

class SignalPollingThread(threading.Thread):
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
            
class DACQC2Sensor:
    def __init__(self,address=1,channel=0):
        self.address = 1
        self.channel = 0
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17,GPIO.OUT)
        GPIO.output(17,1)#set 17 to line-high to reduce noise
        
    def calibrate(self):
        GPIO.output(17,0)
        time.sleep(0.1)
        GPIO.output(17,1)
        
    def read(self):
        for i in range(100):
            try:
                value = DAQC2plate.getADC(self.address,self.channel)
            except IndexError:
                pass
            else:
                return value
        raise ValueError
            
        
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

def SimpleThresholdCB(data,window=5,threshold=1):
    mean = np.mean(data[-window:])
    if mean>threshold:
        print('Above threshold!')
    else:
        print(f'mean={mean}')
            
class CallbackThread(threading.Thread):
    def __init__(self,poll,period=0.1):
        threading.Thread.__init__(self, name='CallbackThread', daemon=True)
        
        self.poll = poll
        self.period = period
        
        self._stop = False
        self._lock = threading.Lock()
        
        self._signal = []
        
    def terminate(self):
        self._stop = True
    
    def process_signal(self,signal):
        pass
        
    def run(self):
        print('Starting runloop for CallbackThread')
        while not self._stop:
            self.process_signal()
            time.sleep(self.period)
            
class StopLoadV1_CB(CallbackThread):
    def __init__(
        self, 
        poll,
        period,
        load_client,
        threshold_npts = 20,
        threshold_v_step = 1,
        threshold_std = 2.5,
        timeout = 120,
        loadstop_cooldown = 2,
        post_detection_sleep = 0.2 ,
        baseline_duration = 10,
    ):
        super().__init__(poll=poll,period=period)
        self.load_client = load_client
        self.threshold_npts = threshold_npts
        self.threshold_v_step = threshold_v_step 
        self.threshold_std =  threshold_std 
        self.loadstop_cooldown =  loadstop_cooldown 
        self.post_detection_sleep = post_detection_sleep 
        self.timeout = datetime.timedelta(seconds=timeout)
        self.baseline_duration = baseline_duration
        
    def process_signal(self):
        if 'PROGRESS' in getServerState(self.load_client):
            print('IT IS MY TIME.  A LOAD IS HAPPENING.')
            start = datetime.datetime.now()
            print(f'Taking baseline data for {self.baseline_duration} s.')
            time.sleep(self.baseline_duration)
            
            signal = self.poll.read()
            
            baseline_val = np.mean(signal[-self.threshold_npts:])
            print(f'Found baseline at {baseline_val}')
            
            while True and (not self._stop):
                signal = self.poll.read()
                condition1 = np.abs(np.mean(signal[-self.threshold_npts:])-baseline_val) < self.threshold_v_step 
                condition2 = np.std(signal[-self.threshold_npts:]) > self.threshold_std
                
                if (condition1 or condition2) and (datetime.datetime.now()-start < self.timeout):
                    time.sleep(self.period)
                else:
                    print(f'Load stopped at voltage mean = {np.mean(signal[-self.threshold_npts:])} and stdev = {np.std(signal[-self.threshold_npts:])}')
                    print(f'Elapsed time: {datetime.datetime.now()-start}')
                    time.sleep(self.post_detection_sleep)
                    self.load_client.server_cmd(cmd='stopLoad',secret='xrays>neutrons')
                    time.sleep(self.loadstop_cooldown)
                    break

            
def getServerState(client):
    for entry in client.driver_status():
        if 'State: ' in entry:
            return entry.replace('State: ','')
        

        
    