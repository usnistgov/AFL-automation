from AFL.automation.APIServer.Client import Client
from AFL.automation.prepare.OT2Client import OT2Client
from AFL.automation.shared.utilities import listify
from AFL.automation.APIServer.Driver import Driver

from math import ceil,sqrt
import json
import time
import requests
import shutil
import datetime
import traceback


class Turbidity_SampleDriver(Driver):
    defaults={}
    defaults['snapshot_directory'] = '/home/nistoroboto'
    def __init__(self,
            load_url,
            prep_url,
            turb_url,
            camera_urls = None,
            snapshot_directory =None,
            overrides=None, 

            ):

        Driver.__init__(self,name='Turbidity_SampleDriver',defaults=self.gather_defaults(),overrides=overrides)

        if not (len(load_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on load_url')

        if not (len(prep_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on prep_url')

        self.app = None
        self.name = 'Turbdity_SampleDriver'

        #prepare samples
        self.prep_client = OT2Client(prep_url.split(':')[0],port=prep_url.split(':')[1])
        self.prep_client.login('SampleServer_PrepClient')
        self.prep_client.debug(False)
        
        #load samples
        self.load_client = Client(load_url.split(':')[0],port=load_url.split(':')[1])
        self.load_client.login('SampleServer_LoadClient')
        self.load_client.debug(False)

        #load samples
        self.turb_url = turb_url
        self.turb_client = Client(turb_url.split(':')[0],port=turb_url.split(':')[1])
        self.turb_client.login('SampleServer')
        self.turb_client.debug(False)

        self.camera_urls = camera_urls

        if snapshot_directory is not None:
            self.config['snapshot_directory'] = snapshot_directory

        self.rinse_uuid = None
        self.prep_uuid = None
        self.catch_uuid = None
        self.load_uuid = None

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0 #seconds


    def status(self):
        status = []
        status.append(f'Snapshots: {self.config["snapshot_directory"]}')
        status.append(f'Cameras: {self.camera_urls}')
        status.append(f'Turb: {self.turb_url}')
        status.append(f'Sample Wait Time: {self.wait_time}')
        status.append(self.status_str)
        return status

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)

    def take_snapshot(self,prefix):
        now = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
        for i,cam_url in enumerate(self.camera_urls):
            fname = self.config['snapshot_directory'] + '/' 
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

    def process_sample(self,sample):
        name = sample['name']

        targets = set()
        for task in sample['prep_protocol']:
            if 'target' in task['source'].lower():
                targets.add(task['source'])
            if 'target' in task['dest'].lower():
                targets.add(task['dest'])

        for task in sample['catch_protocol']:
            if 'target' in task['source'].lower():
                targets.add(task['source'])
            if 'target' in task['dest'].lower():
                targets.add(task['dest'])

        target_map = {}
        for t in targets:
            prep_target = self.prep_client.enqueue(task_name='get_prep_target',interactive=True)['return_val']
            target_map[t] = prep_target

        for task in sample['prep_protocol']:
            #if the well isn't in the map, just use the well
            task['source'] = target_map.get(task['source'],task['source'])
            task['dest'] = target_map.get(task['dest'],task['dest'])
            self.prep_uuid = self.prep_client.transfer(**task)
 
        if self.rinse_uuid is not None:
            self.update_status(f'Waiting for rinse...')
            self.load_client.wait(self.rinse_uuid)
            self.update_status(f'Rinse done!')
            
        self.update_status(f'Cell is clean, measuring empty cell scattering...')
        reference = self.turb_client.enqueue(task_name='measure',set_empty=True,plotting=False,interactive=True)

        
        if self.prep_uuid is not None: 
            self.prep_client.wait(self.prep_uuid)
            self.take_snapshot(prefix = f'02-after-prep-{name}')
        
        self.update_status(f'Queueing sample {name} load into syringe loader')
        for task in sample['catch_protocol']:
            #if the well isn't in the map, just use the well
            task['source'] = target_map.get(task['source'],task['source'])
            task['dest'] = target_map.get(task['dest'],task['dest'])
            self.catch_uuid = self.prep_client.transfer(**task)
        
        if self.catch_uuid is not None:
            self.update_status(f'Waiting for sample prep/catch of {name} to finish: {self.catch_uuid}')
            self.prep_client.wait(self.catch_uuid)
            self.take_snapshot(prefix = f'03-after-catch-{name}')
        
        
        self.load_uuid = self.load_client.enqueue(task_name='loadSample',sampleVolume=sample['volume'])
        self.update_status(f'Loading sample into cell: {self.load_uuid}')
        self.load_client.wait(self.load_uuid)
        self.take_snapshot(prefix = f'05-after-load-{name}')
        
        self.update_status(f'Sample is loaded, asking the instrument for exposure...')
        turbidity, circ_center = self.turb_client.enqueue(task_name='measure',set_empty=False,plotting=False,interactive=True)['return_val']


        self.update_status(f'Cleaning up sample {name}...')
        self.rinse_uuid = self.load_client.enqueue(task_name='rinseCell')

        self.take_snapshot(prefix = f'06-after-measure-{name}')
            
        self.update_status(f'All done for {name}!')
   


   