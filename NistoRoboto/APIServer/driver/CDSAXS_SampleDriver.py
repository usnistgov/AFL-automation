from NistoRoboto.APIServer.client.Client import Client
from NistoRoboto.APIServer.client.OT2Client import OT2Client
from NistoRoboto.shared.utilities import listify
from NistoRoboto.APIServer.driver.Driver import Driver

from math import ceil,sqrt
import json
import time
import requests
import shutil
import datetime
import traceback


class CDSAXS_SampleDriver(Driver):
    def __init__(self,
            load_url,
            prep_url,
            saxs_url,
            camera_urls = None,
            snapshot_directory ='/home/nistoroboto/',
            ):

        if not (len(load_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on load_url')

        if not (len(prep_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on prep_url')

        self.app = None
        self.name = 'SampleDriver'

        #prepare samples
        self.prep_client = OT2Client(prep_url.split(':')[0],port=prep_url.split(':')[1])
        self.prep_client.login('SampleServer_PrepClient')
        self.prep_client.debug(False)
        
        #load samples
        self.load_client = Client(load_url.split(':')[0],port=load_url.split(':')[1])
        self.load_client.login('SampleServer_LoadClient')
        self.load_client.debug(False)

        #load samples
        self.saxs_url = saxs_url
        self.saxs_client = Client(saxs_url.split(':')[0],port=saxs_url.split(':')[1])
        self.saxs_client.login('SampleServer_SAXSClient')
        self.saxs_client.debug(False)

        self.camera_urls = camera_urls
        self.snapshot_directory = snapshot_directory

        self.cell_rinse_uuid = None
        self.catch_rinse_uuid = None
        self.prep_uuid = None
        self.catch_uuid = None

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0 #seconds


    def status(self):
        status = []
        status.append(f'Snapshots: {self.snapshot_directory}')
        status.append(f'Cameras: {self.camera_urls}')
        status.append(f'SAXS: {self.saxs_url}')
        status.append(f'Sample Wait Time: {self.wait_time}')
        status.append(self.status_str)
        return status

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)

    def take_snapshot(self,prefix):
        now = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
        for i,cam_url in enumerate(self.camera_urls):
            fname = self.snapshot_directory + '/' 
            fname += prefix
            fname += f'-{i}-'
            fname += now
            fname += '.jpg'

            try:
                r = requests.get(cam_url,stream=True)
                if r.status_code == 200:
                    with open(fname,'wb') as f:
                        r.raw.decode_content=True
                        shutil.copyfileobj(r.raw,f)
            except Exception as error:
                output_str  = f'take_snapshot failed with error: {error.__repr__()}\n\n'+traceback.format_exc()+'\n\n'
                self.app.logger.warning(output_str)

    def measure(self,sample):
        exposure = sample.get('exposure',None)

        saxs_uuid = self.saxs_client.enqueue(task_name='expose',name=sample['name'],block=True,exposure=exposure)
        return saxs_uuid

    def execute(self,**kwargs):
        if self.app is not None:
            self.app.logger.debug(f'Executing task {kwargs}')

        if kwargs['task_name']=='sample':
            self.process_sample(kwargs)
        elif kwargs['task_name']=='measure':
            self.measure(kwargs)
        elif kwargs['task_name']=='take_snapshot':
            self.take_snapshot(kwargs['prefix'])
        elif kwargs['task_name']=='set_snapshot_directory':
            self.snapshot_directory = kwargs['snapshot_directory']
        elif kwargs['task_name']=='set_wait_time':
            self.wait_time = kwargs['wait_time']
        else:
            raise ValueError(f'Task_name not recognized: {kwargs["task_name"]}')

    def process_sample(self,sample):
        name = sample['name']

        for task in sample['prep_protocol']:
            self.prep_uuid = self.prep_client.transfer(**task)
 
        if self.catch_rinse_uuid is not None:
            self.update_status(f'Waiting for catch rinse...')
            self.load_client.wait(self.catch_rinse_uuid)
            self.update_status(f'Catch rinse done!')
            
        if self.prep_uuid is not None: 
            self.prep_client.wait(self.prep_uuid)
            self.take_snapshot(prefix = f'02-after-prep-{name}')
        
        self.update_status(f'Queueing sample {name} load into syringe loader')
        for task in sample['catch_protocol']:
            self.catch_uuid = self.prep_client.transfer(**task)
        
        if self.catch_uuid is not None:
            self.update_status(f'Waiting for sample prep/catch of {name} to finish: {self.catch_uuid}')
            self.prep_client.wait(self.catch_uuid)
            self.take_snapshot(prefix = f'03-after-catch-{name}')
        
        if self.cell_rinse_uuid is not None:
            self.update_status(f'Waiting for cell rinse: {self.cell_rinse_uuid}')
            self.load_client.wait(self.cell_rinse_uuid)
            self.take_snapshot(prefix = f'04-after-cell-rinse-{name}')
            self.update_status(f'Cell rinse done!')
        
        self.load_uuid = self.load_client.enqueue(task_name='loadSample',sampleVolume=sample['volume'])
        self.update_status(f'Loading sample into cell: {self.load_uuid}')
        self.load_client.wait(self.load_uuid)
        self.take_snapshot(prefix = f'05-after-load-{name}')
        
        self.update_status(f'Queueing catch rinse...')
        self.catch_rinse_uuid = self.load_client.enqueue(task_name='rinseCatch')

        self.update_status(f'Sample is loaded, asking the SAXS for exposure...')
        self.saxs_uuid = self.measure(sample)
        self.update_status(f'Waiting for CDSAXS to measure scattering of {name} with UUID {self.saxs_uuid}...')
        self.saxs_client.wait(self.saxs_uuid)
        self.take_snapshot(prefix = f'06-after-measure-{name}')
            
        self.update_status(f'Cleaning up sample {name}...')
        self.load_client.enqueue(task_name='rinseCell')
        self.load_client.enqueue(task_name='rinseSyringe')
        self.cell_rinse_uuid =  self.load_client.enqueue(task_name='blowOutCell')
        
        self.update_status(f'All done for {name}!')
   






   
