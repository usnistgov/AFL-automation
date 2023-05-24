import numpy as np
import warnings
import threading
import time
import datetime
import pathlib

            
class SensorCallbackThread(threading.Thread):
    def __init__(self,poll,period=0.1,daemon=True,filepath=None,data=None):
        threading.Thread.__init__(self, name='CallbackThread', daemon=daemon)

        self.app = None
        self.data = data

        self.poll = poll
        self.period = period

        self.thread_start = datetime.datetime.now()
        
        self._stop = False
        self._lock = threading.Lock()
        
        self._signal = []
        self.status_str = 'No action yet...'

        if filepath is not None:
            self.filepath = pathlib.Path(filepath)
            self.filepath.mkdir(parents=True, exist_ok=True)

    def update_status(self,value):
        self.status_str = value
        if self.app is not None:
            self.app.logger.info(value)
        else:
            print(value)

        
    def terminate(self):
        self._stop = True
    
    def process_signal(self,signal):
        pass
        
    def run(self):
        print('Starting runloop for CallbackThread:')
        while not self._stop:
            dt = datetime.datetime.now()-self.thread_start
            # print(f'Running for {dt.seconds:010d} seconds',end='\r')
            self.process_signal()
            time.sleep(self.period)

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
        baseline_duration = 2,
        daemon=True,
        filepath=None,
        data=None,
    ):
        super().__init__(poll=poll,period=period,daemon=daemon,filepath=filepath,data=data)
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
            datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y%m%d-%H:%M:%S')
            self.update_status(f'[{datestr}] Detected a load...')
            start = datetime.datetime.now()
            self.update_status(f'Taking baseline data for {self.baseline_duration} s.')
            time.sleep(self.baseline_duration)
            
            signal = self.poll.read()
            
            baseline_val = np.mean(signal[-self.threshold_npts:])
            self.update_status(f'Found baseline at {baseline_val}')
            
            while True and (not self._stop):
                signal = self.poll.read()
                voltage_not_changed = np.abs(np.mean(signal[-self.threshold_npts:])-baseline_val) < self.threshold_v_step 
                signal_unstable = np.std(signal[-self.threshold_npts:]) > self.threshold_std
                not_timed_out = datetime.datetime.now()-start < self.timeout
                
                if (voltage_not_changed or signal_unstable) and not_timed_out:
                    time.sleep(self.period)
                else:
                    datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y%m%d-%H:%M:%S')
                    if not_timed_out:
                        self.update_status(f'[{datestr}] Load stopped at voltage mean = {np.mean(signal[-self.threshold_npts:])} and stdev = {np.std(signal[-self.threshold_npts:])}')
                    else:
                        self.update_status(f'[{datestr}] Load timed out')
                    self.update_status(f'Elapsed time: {datetime.datetime.now()-start}')
                    elapsed_time = datetime.datetime.now()-start
                    time_to_sleep = (self.post_detection_sleep)*elapsed_time
                    
                    time.sleep(time_to_sleep.total_seconds()) # was self.post_detection_sleep)
                    
                    print(f'waited for {time_to_sleep.total_seconds()} based on elapsed time of {elapsed_time.total_seconds()} and ratio of {self.post_detection_sleep*100} %')
                    self.load_client.server_cmd(cmd='stopLoad',secret='xrays>neutrons')

                    filename = self.filepath/str('Sensor-'+datestr+'.txt')
                    self.update_status(f'Saving signal data to {filename}')
                    np.savetxt(filename,signal)

                    if self.data is not None:
                        self.data['load_stop_trace'] = signal
                        self.data['final_voltage'] = np.mean(signal[-self.threshold_npts:])

                    time.sleep(self.loadstop_cooldown)
                    break

class StopLoadCBv2(SensorCallbackThread):
    def __init__(
        self, 
        poll,
        period,
        load_client=None,
        load_object=None,
        threshold_npts = 20,
        threshold_v_step = 1,
        threshold_std = 2.5,
        timeout = 120,
        min_load_time=30,
        loadstop_cooldown = 2,
        post_detection_sleep = 0.2 ,
        baseline_duration = 2,
        trigger_on_end = False,
        instatrigger = True,
        daemon=True,
        filepath=None,
        data=None,
    ):
        super().__init__(poll=poll,period=period,daemon=daemon,filepath=filepath,data=data)
        self.loader_comm = LoaderCommunication(load_client=load_client,load_object=load_object)
        self.threshold_npts = threshold_npts
        self.threshold_v_step = threshold_v_step 
        self.threshold_std =  threshold_std 
        self.loadstop_cooldown =  loadstop_cooldown 
        self.post_detection_sleep = post_detection_sleep 
        self.min_load_time = datetime.timedelta(seconds=min_load_time)
        self.timeout = datetime.timedelta(seconds=timeout)
        self.baseline_duration = baseline_duration
        self.trigger_on_end = trigger_on_end
        self.instatrigger = instatrigger

        print(f'StopLoad thread starting with data = {self.data}')

    def process_signal(self):
        if 'PROGRESS' in self.loader_comm.getServerState():
            datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y%m%d-%H:%M:%S')
            self.update_status(f'[{datestr}] Detected a load...')
            start = datetime.datetime.now()

            self.poll.reset_load_buffer()

            self.update_status(f'Taking baseline data for {self.baseline_duration} s.')
            time.sleep(self.baseline_duration)
            
            signal = np.array(self.poll.read_load_buffer())
            
            baseline_val = np.mean(signal[-self.threshold_npts:,1])#column 0 is microseconds since beginning of load
            self.update_status(f'Found baseline at {baseline_val}')
            if self.data is not None:
                self.data['stopper_baseline_voltage'] = baseline_val
            while True and (not self._stop):
                signal = np.array(self.poll.read_load_buffer())

                small_v_step = np.abs(np.mean(signal[-self.threshold_npts:,1])-baseline_val) < self.threshold_v_step 
                large_std = np.std(signal[-self.threshold_npts:,1]) > self.threshold_std

                time_since_load_start = datetime.datetime.now()-start 
                timed_out = time_since_load_start > self.timeout
                too_soon = time_since_load_start < self.min_load_time
                
                if too_soon:
                    time.sleep(self.period)
                elif (small_v_step or large_std) and (not timed_out):
                    time.sleep(self.period)
                else:
                    datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y%m%d-%H:%M:%S')
                    self.update_status(f'Elapsed time: {datetime.datetime.now()-start}')
                    if not timed_out:
                        self.update_status(f'[{datestr}] Load stopped at voltage mean = {np.mean(signal[-self.threshold_npts:,1])} and stdev = {np.std(signal[-self.threshold_npts:,1])}')
                    else:
                        self.update_status(f'[{datestr}] Load timed out')
                    
                    
                    elapsed_time = datetime.datetime.now()-start
                    if self.data is not None:
                        self.data['elapsed_time_at_first_trigger'] = elapsed_time.total_seconds()
                        self.data['first_trigger_voltage'] = np.mean(signal[-self.threshold_npts:,1])
                        self.data['first_trigger_std'] = np.std(signal[-self.threshold_npts:,1])

                    if self.trigger_on_end:
                        self.update_status(f'[{datestr}] Awaiting stabilized return to within {self.threshold_v_step} V of baseline voltage of {baseline_val} V')
                        second_trigger_start = datetime.datetime.now()
                        while not self._stop:
                            time_since_second_trigger = datetime.datetime.now() - second_trigger_start
                            timed_out = time_since_second_trigger > self.timeout

                            mean_not_normal = np.abs(np.mean(signal[-self.threshold_npts:,1])-baseline_val) > 3*self.threshold_v_step 
                            large_std = False #np.std(signal[-self.threshold_npts:,1]) > self.threshold_std
                            
                            if (mean_not_normal or large_std) and (not timed_out):
                                time.sleep(self.period/10)
                            else:
                                datestr = datetime.datetime.strftime(datetime.datetime.now(),'%y%m%d-%H:%M:%S')
                                self.update_status(f'[{datestr}] End of plug triggered at voltage mean {np.mean(signal[-self.threshold_npts:,1])} and stdev = {np.std(signal[-self.threshold_npts:,1])}')
                                if self.data is not None:
                                    self.data['elapsed_time_at_second_trigger'] = (datetime.datetime.now()-start).total_seconds()
                                    self.data['second_trigger_voltage'] = np.mean(signal[-self.threshold_npts:,1])
                                    self.data['second_trigger_std'] = np.std(signal[-self.threshold_npts:,1])
                                break

                    elif self.instatrigger:
                        pass
                    else:    
                        time_to_sleep = (self.post_detection_sleep)*elapsed_time
                    
                        time.sleep(time_to_sleep.total_seconds()) # was self.post_detection_sleep)

                        print(f'waited for {time_to_sleep.total_seconds()} based on elapsed time of {elapsed_time.total_seconds()} and ratio of {self.post_detection_sleep} %')

                    self.loader_comm.stopLoad()
                    filename = self.filepath/str('Sensor-'+datestr+'.txt')
                    # self.update_status(f'Saving signal data to {filename}')
                    np.savetxt(filename,signal)
                    if self.data is not None:
                        self.data['load_stop_trace'] = signal
                        self.data['final_voltage'] = np.mean(signal[-self.threshold_npts:,1])
                        self.data['final_std'] = np.std(signal[-self.threshold_npts:,1])

                    time.sleep(self.loadstop_cooldown)
                    break

class SimpleThresholdCB(SensorCallbackThread):
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
            
class LoaderCommunication():

    def __init__(self,load_client=None,load_object=None):
        if (load_client is None) and (load_object is None):
            raise ValueError('Need to specify load_client or load_object!!')
        elif (load_client is not None) and (load_object is not None):
            warnings.warn('Both load_client and load_object were specified! Using load_object...')
            self.load_object = load_object
            self.load_client = None
        elif load_client is None:
            self.load_object = load_object
            self.load_client = None
        else:
            self.load_object = None
            self.load_client = load_client
            
    def getServerState(self):
        if self.load_client is None:
            status = self.load_object.status()
        else:
            status = self.load_client.driver_status()
                
        for entry in status:
            if 'State: ' in entry:
                return entry.replace('State: ','')
        
    def stopLoad(self):
        if self.load_client is None:
            self.load_object.stopLoad(secret='xrays>neutrons')
        else:
            self.load_client.server_cmd(cmd='stopLoad?secret=xrays>neutrons')

        
    
