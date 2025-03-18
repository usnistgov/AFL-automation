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


class CastingServer(Driver):
    defaults={}
    defaults['manifest'] = '/home/afl642/'
    defaults['manifest_prep'] = '/home/afl642/'
    defaults['manifest_cast'] = '/home/afl642/'
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
        
        # sample_name --> location mapping
        self.prepare_locs = {}
        self.cast_locs = {}
        
        self.prep_uuid = None

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0 #seconds
        self.init_casting_manifest()

    def init_casting_manifest(self,attrs=None,overwrite=False):
        self.manifests = {}
        for manifest in ['manifest','manifest_prep','manifest_cast']:
            print(f'Trying to load {self.config[manifest]}')
            if not overwrite:
                try:
                    self.manifests[manifest] = xr.load_dataset(self.config[manifest])
                    print(f'Loaded!')
                except (FileNotFoundError,ValueError):
                    self.manifests[manifest] = xr.Dataset()
                    print(f'Not Found...starting new manifest')
            else:
                self.manifests[manifest] = xr.Dataset()
                print(f'Starting new manifest')

            if attrs is not None:
                self.manifests[manifest].attrs.update(attrs)

    def status(self):
        status = []
        status.append(self.status_str)
        return status

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)
    
    def log_event(self,manifest_key,event,write=True):
        #event['started'] = datetime.datetime.strptime(event['started'],'%m/%d/%y %H:%M:%S-%f')
        #event['ended'] = datetime.datetime.strptime(event['ended'],'%m/%d/%y %H:%M:%S-%f')
        
        ds_event = xr.Dataset()
        for k,v in event.items():
            ds_event[k] = ('event',v)
        
        self.manifests[manifest_key] = xr.concat([
            self.manifests[manifest_key],
            ds_event
        ], 
            dim='event'
        )
        
        if write:
            self.manifests[manifest_key].to_netcdf(self.config[manifest_key])
            self.manifests[manifest_key].to_pandas().to_csv(self.config[manifest_key].replace('nc','csv'))
            
    def assign_targets(self,protocols,target_map):
        if target_map is None:
            self.targets = set()
            for name,protocol in protocols.items():
                for task in protocol:
                    if 'target' in task['source'].lower():
                        self.targets.add(task['source'])
                    if 'target' in task['dest'].lower():
                        self.targets.add(task['dest'])
    
            self.target_map = {}
            for t in self.targets:
                prep_target = self.prep_client.enqueue(task_name='get_prep_target',interactive=True)['return_val']
                self.target_map[t] = prep_target
        else:
            self.target_map = target_map

        for name,protocol in protocols.items():
            for task in protocol:
                task['source'] = self.target_map.get(task['source'],task['source'])
                task['dest'] = self.target_map.get(task['dest'],task['dest'])
                
        return protocols
    
    def prepare_casting_stocks(self,**spec):
        '''Spec should contain sample_name and a protocol'''
        self.init_casting_manifest()
        manifest = self.manifests['manifest_prep']
        
        stock_name = spec['stock_name']
        sample_names = spec['sample_names']
        protocol = spec['protocol']
        
        for sample_name,task in zip(sample_names,protocol):
            self.update_status(f'Transferring {task["volume"]} uL from {task["source"]} to {task["dest"]}')
            self.last_prep = self.prep_client.transfer(interactive=True,**task)
            self.last_prep_time = self.last_prep['ended'] 
            
            self.last_prep['event_type'] = 'prep'
            self.last_prep['sample_name'] = sample_name
            self.last_prep['stock_name'] = stock_name
            self.last_prep.update(**task)
            self.log_event('manifest_prep',self.last_prep)
            
    def bulk_cast_films(self,**spec):
        '''Spec should contain sample_name and a protocol'''
        self.init_casting_manifest()
        manifest = self.manifests['manifest_cast']
        
        sample_names = spec['sample_names']
        plate_names = spec['plate_names']
        protocol = spec['protocol']
        if not ( (len(sample_names)==len(plate_names)) and (len(sample_names)==len(protocol))):
            raise ValueError('Number of plate_names,sample_names, and protocols must be equal')
        
        for sample_name,plate_name,task in zip(sample_names,plate_names,protocol):
            self.update_status(f'Transferring {task["volume"]} uL from {task["source"]} to {task["dest"]}')
            self.last_prep = self.prep_client.transfer(interactive=True,**task)
            self.last_prep_time = self.last_prep['ended'] 
            
            self.last_prep['event_type'] = 'cast'
            self.last_prep['sample_name'] = sample_name
            self.last_prep['plate_name'] = plate_name
            self.last_prep.update(**task)
            self.log_event('manifest_cast',self.last_prep)

    def prepare_and_cast(self,**sample):
        self.init_casting_manifest()
        
        sample_name = sample['sample_name']
        plate_names = sample['plate_names']
        #stock_name = sample['stock_name']
        # protocols = self.assign_targets({k:sample[k] for k in ['prep_protocol','cast_protocol']})
        protocols = {k:sample[k] for k in ['prep_protocol','cast_protocol']}

        self.update_status(f'Preparing sample: {sample_name}')
        for task in protocols['prep_protocol']:
            self.update_status(f'Transferring {task["volume"]} uL from {task["source"]} to {task["dest"]}')
            self.last_prep = self.prep_client.transfer(interactive=True,**task)
            self.last_prep_time = self.last_prep['ended'] 
            
            self.last_prep['event_type'] = 'prep'
            self.last_prep['sample_name'] = sample_name
            #self.last_prep['stock_name'] = stock_name
            self.last_prep.update(**task)
            #self.log_event('manifest_prep',self.last_prep)
            
        # shouldn't have to wait, but let's do this for safety
        if self.prep_uuid is not None: 
            self.prep_client.wait(self.prep_uuid)

        # if 'min_mix_time' in sample:
        #     try:
        #         if not (len(sample['min_mix_time'])==len(sample['cast_protocol'])):
        #             raise ValueError(f'min_mix_time has multiple values, but does not match length of cast protocol len(sample["cast_protocol"]')
        #     except TypeError:
        #         #value is scalar, make vector
        #         sample['min_mix_time'] = [sample['min_mix_time']]*len(sample['cast_protocol'])
        # else:
        #     sample['min_mix_time'] = [0.0]*len(sample['cast_protocol'])
        #     

        self.update_status(f'Casting sample: {sample_name}')
        for plate_name,task in zip(plate_names,protocols['cast_protocol']):
            
            # delta = datetime.timedelta(seconds=min_mix_time)
            # self.update_status(f'Waiting for min_mix_time to be satisfied: {min_mix_time} s')
            # while (datetime.datetime.now()-self.last_prep['ended'])<delta:
            #     time.sleep(0.05)
            # actual_mix_time = datetime.datetime.now()-self.last_prep['ended']
                
            self.update_status(f'Transferring {task["volume"]} uL from {task["source"]} to {task["dest"]}')
            self.last_prep = self.prep_client.transfer(**task,interactive=True)

            self.last_prep['event_type'] = 'cast'
            self.last_prep['sample_name'] = sample_name
            self.last_prep['plate_name'] = plate_name
            self.last_prep.update(**task)
            #self.log_event('manifest_cast',self.last_prep)
            self.update_status(f'Cast {self.last_prep["sample_name"]}!')
            
        
        self.update_status(f'All done for sample {sample_name} on plate {plate_name}!')
   



_DEFAULT_CUSTOM_CONFIG = {
        '_classname': 'AFL.automation.sample.CastingServer.CastingServer',
        'prep_url': 'localhost:5000'
}
_DEFAULT_CUSTOM_PORT = 5000
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *


   
