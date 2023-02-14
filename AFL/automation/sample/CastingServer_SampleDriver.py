from AFL.automation.APIServer.Client import Client
from AFL.automation.prepare.OT2Client import OT2Client
from AFL.automation.shared.utilities import listify
from AFL.automation.APIServer.Driver import Driver

from math import ceil,sqrt
import json
import datetime,time
import requests
import shutil
import datetime
import traceback

import xarray as xr


class CastingServer_SampleDriver(Driver):
    defaults={}
    defaults['manifest'] = '/home/afl642/'
    def __init__(self,
            prep_url,
            overrides=None, 
            ):

        Driver.__init__(self,name='CastingServer_SampleDriver',defaults=self.gather_defaults(),overrides=overrides)

        self.app = None
        self.name = 'CastingServer_SampleDriver'

        if not (len(prep_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on prep_url')

        #prepare samples
        self.prep_client = OT2Client(prep_url.split(':')[0],port=prep_url.split(':')[1])
        self.prep_client.login('SampleServer_PrepClient')
        self.prep_client.debug(False)
        
        self.prep_uuid = None

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0 #seconds
        self.init_casting_manifest()

    def init_casting_manifest(self,overrite=False):
        try:
            self.manifest = xr.load_dataset(self.config['manifest'])
        except FileNotFoundError:
            self.manifest = xr.Dataset()

    def status(self):
        status = []
        status.append(self.status_str)
        return status

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)
    
    def log_event(self,event,write=True):
        event['started'] = datetime.datetime.strptime(event['started'],'%m/%d/%y %H:%M:%S-%f')
        event['ended'] = datetime.datetime.strptime(event['ended'],'%m/%d/%y %H:%M:%S-%f')
        
        ds_event = xr.Dataset()
        for k,v in event.items():
            ds_event[k] = v
        
        self.manifest = xr.concat([self.manifest,ds_event],dim='event')
        
        if write:
            self.manifest.to_netcdf(self.config['manifest'])
            self.manifest.to_pandas().to_csv(self.config['manifest'].replace('nc','csv'))

    def cast_film(self,**sample):
        sample_name = sample['sample_name']
        plate_name = sample['plate_name']

        targets = set()
        for task in sample['prep_protocol']:
            if 'target' in task['source'].lower():
                targets.add(task['source'])
            if 'target' in task['dest'].lower():
                targets.add(task['dest'])

        for task in sample['cast_protocol']:
            if 'target' in task['source'].lower():
                targets.add(task['source'])
            if 'target' in task['dest'].lower():
                targets.add(task['dest'])

        target_map = {}
        for t in targets:
            prep_target = self.prep_client.enqueue(task_name='get_prep_target',interactive=True)['return_val']
            target_map[t] = prep_target

        self.update_status(f'Preparing sample: {sample_name}')
        for task in sample['prep_protocol']:
            #if the well isn't in the map, just use the well from the user
            task['source'] = target_map.get(task['source'],task['source'])
            task['dest'] = target_map.get(task['dest'],task['dest'])
            self.update_status(f'Transferring {task["volume"]} uL from {task["source"]} to {task["dest"]}')
            self.last_prep = self.prep_client.transfer(interactive=True,**task)
            self.last_prep_time = self.last_prep['ended'] 
            
            self.last_prep['sample_name'] = sample_name
            self.last_prep['plate_name'] = plate_name
            self.last_prep['event_type'] = 'transfer'
            self.last_prep.update(**task)
            self.log_event(self.last_prep)
            
        # shouldn't have to wait, but let's do this for safety
        if self.prep_uuid is not None: 
            self.prep_client.wait(self.prep_uuid)

        # if 'min_mix_time_sec' in sample:
        #     delta = datetime.timedelta(seconds=sample['min_mix_time_sec'])
        #     self.update_status(f'Waiting for min_mix_time_sec to be satisfied: {sample["min_mix_time_sec"]}')
        #     while (datetime.datetime.now()-self.last_prep['ended'])<delta:
        #         time.sleep(0.05)
                
        if 'min_mix_time' in sample:
            try:
                if not (len(sample['min_mix_time'])==len(sample['cast_protocol'])):
                    raise ValueError(f'min_mix_time has multiple values, but does not match length of cast protocol len(sample["cast_protocol"]')
            except TypeError:
                #value is scalar, make vector
                sample['min_mix_time'] = [sample['min_mix_time']]*len(sample['cast_protocol'])
        else:
            sample['min_mix_time'] = [0.0]*len(sample['cast_protocol'])
            

        self.update_status(f'Casting sample: {sample_name}')
        for task,min_mix_time in zip(sample['cast_protocol'],sample['min_mix_time']):
            
            delta = datetime.timedelta(seconds=min_mix_time)
            self.update_status(f'Waiting for min_mix_time to be satisfied: {min_mix_time} s')
            while (datetime.datetime.now()-self.last_prep['ended'])<delta:
                time.sleep(0.05)
                
            task['dest'] = target_map.get(task['dest'],task['dest'])
            self.update_status(f'Transferring {task["volume"]} uL from {task["source"]} to {task["dest"]}')
            self.last_prep = self.prep_client.transfer(**task,interactive=True)

            self.last_prep['sample_name'] = sample_name
            self.last_prep['plate_name'] = plate_name
            self.last_prep['event_type'] = 'cast'
            self.last_prep.update(**task)
            self.log_event(self.last_prep)
        
        self.update_status(f'All done for sample {sample_name} on plate {plate_name}!')
   






   
