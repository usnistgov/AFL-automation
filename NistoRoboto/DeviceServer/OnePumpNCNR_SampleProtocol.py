from NistoRoboto.DeviceServer.Client import Client
from NistoRoboto.DeviceServer.OT2Client import OT2Client
from NistoRoboto.shared.utilities import listify

# import nice

from math import ceil,sqrt
import json
import time


class OnePumpNCNRProtocol:
    def __init__(self,
            load_url,
            prep_url,
            nice_url='NGBSANS.ncnr.nist.gov',
            ):

        if not (len(load_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on load_url')

        if not (len(prep_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on prep_url')

        self.app = None
        self.name = 'OnePumpNCNR'

        #prepare samples
        self.prep_client = OT2Client(prep_url.split(':')[0],port=prep_url.split(':')[1])
        self.prep_client.login('SampleServer_PrepClient')
        self.prep_client.debug(False)
        
        #load samples
        self.load_client = Client(load_url.split(':')[0],port=load_url.split(':')[1])
        self.load_client.login('SampleServer_LoadClient')
        self.load_client.debug(False)

        #measure samples
        self.nice_client = None# nice.connect(host='NGBSANS.ncnr.nist.gov')

        self.cell_rinse_uuid = None
        self.catch_rinse_uuid = None

        self.default_nice_params ={
                'counter.countAgainst':'TIME',
                'groupid':'-1', 
                'filePurpose':'SCATTERING', 
                'sample.thickness':'1.0', 
                    
                } 

        self.status_str = ''
    def status(self):
        return [self.status_str]

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)

    def execute(self,**kwargs):
        if self.app is not None:
            self.app.logger.debug(f'Executing task {kwargs}')

        if 'sample' in kwargs:
            self.process_sample(kwargs)

    def measure(self,sample):
        runGroup = sample.get('nice_runGroup',10)
        prefix = sample.get('nice_prefix','ROBOT')
        user = sample.get('nice_user','NGB')

        for config in sample['configs']:
            nice_params = self.default_nice_params.copy()
            nice_params.update(config)
            params_str = json.dumps(nice_params).replace(':','=')

            # self.nice_client.console(f'runPoint {params_str} -g {runGroup} -p \"{prefix}\" -u \"{user}\"')

    def process_sample(self,sample):
        name = sample['sampl']

        for task in sample['protocol']:
            kw = task.get_kwargs()
            self.prep_uuid = self.prep_client.transfer(**kw)
 
        if self.catch_rinse_uuid is not None:
            self.update_status(f'Waiting for catch rinse...')
            self.load_client.wait(self.catch_rinse_uuid)
            self.update_status(f'Catch rinse done!')
        
        self.update_status(f'Queueing sample {name} load into syringe loader')
        self.catch_uuid = self.prep_client.transfer(**{
            'source':sample['target_loc'],
            'dest':sample['catch_loc'],
            'volume':sample['volume']*1000,
            })
        
        self.update_status(f'Waiting for sample prep/catch of {name} to finish')
        self.prep_client.wait(self.catch_uuid)
        
        if self.cell_rinse_uuid is not None:
            self.update_status(f'Waiting for cell rinse...')
            self.load_client.wait(self.cell_rinse_uuid)
            # time.sleep(10)
            # take_image(cam,prefix='camera/200809/',tag = f'cleaned-{conc:5.4f}')
            self.update_status(f'Cell rinse done!')
        
        self.update_status(f'Loading sample into cell...')
        self.load_uuid = self.load_client.enqueue(task_name='loadSample',sampleVolume=sample['volume'])
        self.load_client.wait(self.load_uuid)
        # time.sleep(10)
        # take_image(cam,prefix='camera/200809/',tag = f'loaded-{conc:5.4f}')
        
        self.update_status(f'Queueing catch rinse')
        self.catch_rinse_uuid = self.load_client.enqueue(task_name='rinseCatch')

        self.update_status(f'Asking NICE to measure sample {name}')
        self.measure(sample)
        self.update_status(f'Waiting for NICE to measure scattering of {name}')
        time.sleep(60)
        # while str(self.nice_client.queue.queue_state) != 'IDLE':
        #     time.sleep(10)
            
        self.update_status(f'Cleaning up sample {name}')
        self.load_client.enqueue(task_name='rinseCell')
        self.cell_rinse_uuid = self.load_client.enqueue(task_name='blowOutCell')
        
        self.update_status(f'All done for {name}')
   






   
