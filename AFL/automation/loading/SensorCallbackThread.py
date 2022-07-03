import numpy as np
import threading
import time
import datetime
import pathlib

            
class SensorCallbackThread(threading.Thread):
    def __init__(self,poll,period=0.1,daemon=True,filepath=None):
        threading.Thread.__init__(self, name='CallbackThread', daemon=daemon)
        
        self.poll = poll
        self.period = period
        
        self._stop = False
        self._lock = threading.Lock()
        
        self._signal = []

        if filepath is not None:
            self.filepath = pathlib.Path(filepath)
            self.filepath.mkdir(parents=True, exist_ok=True)
        
    def terminate(self):
        self._stop = True
    
    def process_signal(self,signal):
        pass
        
    def run(self):
        i=0
        print('Starting runloop for CallbackThread:')
        while not self._stop:
            print(f'Callback iteration {i:010d}',end='\r')
            self.process_signal()
            time.sleep(self.period)
            i+=1

class StopLoadCBv1(SensorCallbackThread):
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
        daemon=True,
        filepath=None,
    ):
        super().__init__(poll=poll,period=period,daemon=daemon,filepath=filepath)
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
            datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y/%m/%d-%H:%M:%S')
            print(f'[{datestr}] Detected a load...')
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
                condition3 = datetime.datetime.now()-start < self.timeout
                
                if (condition1 or condition2) and condition3:
                    time.sleep(self.period)
                else:
                    datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y/%m/%d-%H:%M:%S')
                    if condition3:
                        print(f'[{datestr}] Load timed out')

                    else:
                        print(f'[{datestr}] Load stopped at voltage mean = {np.mean(signal[-self.threshold_npts:])} and stdev = {np.std(signal[-self.threshold_npts:])}')
                    print(f'Elapsed time: {datetime.datetime.now()-start}')
                    time.sleep(self.post_detection_sleep)
                    self.load_client.server_cmd(cmd='stopLoad',secret='xrays>neutrons')

                    filename = self.filepath/'Sensor-'+datestr+'.txt'
                    print(f'Saving signal data to {filename}')
                    np.savetxt(filename,signal)

                    time.sleep(self.loadstop_cooldown)
                    break

class SimpleThreshholdCB(SensorCallbackThread):
    def __init__(self,poll,period,window=5,threshold=1):
        super().__init__(poll=poll,period=period)
        self.window = window
        self.threshold = threshold
    def process_signal(self):
        signal = self.poll.read()
        mean = np.mean(signal[-window:])
        if mean>threshold:
            print('Above threshold!')
        else:
            print(f'mean={mean}')
            
def getServerState(client):
    for entry in client.driver_status():
        if 'State: ' in entry:
            return entry.replace('State: ','')
        

        
    
