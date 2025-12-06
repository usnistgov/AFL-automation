import time
import functools
import threading
import time
import datetime
import os
import sys
import traceback
import subprocess
import json
import pathlib
import numpy as np
import pandas as pd
import xarray as xr
from AFL.automation.shared.serialization import is_serialized
from AFL.automation.APIServer.data.DataTrashcan import DataTrashcan

class QueueDaemon(threading.Thread):
    '''
    '''

    def __init__(self, app, driver, task_queue, history, debug=False, data = None):
        app.logger.info('Creating QueueDaemon thread')

        threading.Thread.__init__(self, name='QueueDaemon', daemon=True)

        self.driver = driver

        self.app = app
        self.task_queue = task_queue
        self.history = history #history local to this server restart
        self.running_task = []

        self.stop = False
        self.debug = debug
        self.paused = False
        self.busy = False  # flag denotes if a task is being processed
    
        if data is None:
            self.data = DataTrashcan()
        else:
            self.data = data

        self.data['driver_name'] = driver.name
        self.data['driver_config'] = driver.config.config
        try:
            self.data['platform_serial'] = os.environ['AFL_SYSTEM_SERIAL']
        except KeyError:
            self.data['platform_serial'] = 'not_set'
        try:
            self.data['afl_automation_version'] = subprocess.check_output(["git", "describe", "--always"]).strip().decode()
        except Exception:
            self.data['afl_automation_version'] = 'could_not_determine'


    def terminate(self):
        self.app.logger.info('Terminating QueueDaemon thread')
        self.stop = True
        self.task_queue.put(None)
        
    def check_if_paused(self):
        # pause queue but notify user of state every minute
        count = 600
        while self.paused:
            time.sleep(0.1)
            count+=1
            if count>600:
                self.app.logger.info((
                    'Queued is paused. '
                    'Set paused state to false to continue execution'
                ))
                count = 0

    def mask_serialized_objs(self,package):
        masked_package = {'task':{}}
        if 'meta' in package:
            masked_package['meta'] = package['meta']
        if 'uuid' in package:
            masked_package['uuid'] = str(package['uuid'])

        for k,v in package['task'].items():
            if is_serialized(v):
                masked_package['task'][k] = 'serialized_object'
            else:
                masked_package['task'][k] = v
        return masked_package
        

    def run(self):
        self.app.logger.info('Initializing QueueDaemon run-loop')
        while not self.stop:
            self.check_if_paused()

            self.app.logger.debug('Getting item from queue')
            package = self.task_queue.get(block=True, timeout=None)
            self.app.logger.debug('Got item from queue')
            
            # If the task object is None, break the queue-loop
            if package is None:  # stop the queue execution
                self.terminate()
                break

            self.busy = True
            task = package['task']
            self.app.logger.info(f'Running task {task}')
            start_time = datetime.datetime.now()
            masked_package = self.mask_serialized_objs(package)
            #masked_package['meta']['started'] = start_time.strftime('%H:%M:%S')
            masked_package['meta']['started'] = start_time.strftime('%m/%d/%y %H:%M:%S-%f %Z%z')
            self.running_task = [masked_package]
            
            self.check_if_paused()

            # if debug_mode, pop and wait but don't execute
            if self.debug:
                time.sleep(3.0)
                return_val = None
                exit_state = 'Debug Mode!'
            else:

                try:
                    self.driver.pre_execute(**task)
                    self.data['driver_config'].update(self.driver.config.config)
                    self.data.update(task)
                    self.data['status_before'] = self.driver.status()
                    #ops_thread = threading.Thread(target=self.driver.execute,kwargs=task)
                    return_val = self.driver.execute(**task)
                    self.driver.post_execute(**task)
                    exit_state = 'Success!'
                except Exception as error:
                    return_val = f'Error: {error.__repr__()}\n\n' + traceback.format_exc() + '\n\n'
                    return_val += 'Exception encountered in driver.execute, pausing queue...'
                    exit_state = 'Error!'
                    self.app.logger.error(return_val)
                    self.paused = True
            self.data['status_after'] = self.driver.status()
            end_time = datetime.datetime.now()
            run_time = end_time - start_time
            masked_package['meta']['ended'] = end_time.strftime('%m/%d/%y %H:%M:%S-%f %Z%z')
            masked_package['meta']['run_time_seconds'] = run_time.seconds
            masked_package['meta']['run_time_minutes'] = run_time.seconds/60
            masked_package['meta']['exit_state'] = exit_state
            if isinstance(return_val,np.ndarray):
                masked_package['meta']['return_val'] = return_val.tolist()
            elif isinstance(return_val,pd.Series):
                masked_package['meta']['return_val'] = return_val.tolist()
            elif isinstance(return_val,xr.Dataset):
                masked_package['meta']['return_val'] = 'xarray.Dataset'
            else:
                masked_package['meta']['return_val'] = return_val
            masked_package['uuid'] = str(masked_package['uuid'])
            self.running_task = []
            
            self.data.update(masked_package)

            # the following block names the return value a special name
            # so that DataTiled can store it as the main data element

            if isinstance(return_val, xr.Dataset):
                self.data['main_dataset'] = return_val
            elif type(return_val) is np.ndarray:
                self.data['main_array'] = return_val
            elif type(return_val) is pd.DataFrame:
                self.data['main_dataframe'] = return_val
            elif type(return_val) is pd.Series:
                self.data['main_dataframe'] = return_val.to_frame()

            self.data.finalize()
            self.history.append(masked_package)#history for this server restart

            self.task_queue.iteration_id = time.time()
            # mark queue iteration as changed
            
            self.busy = False
            time.sleep(0.1)

        self.app.logger.info('QueueDaemon runloop exiting')
