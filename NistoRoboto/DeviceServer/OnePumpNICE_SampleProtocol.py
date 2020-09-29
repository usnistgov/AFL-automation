from NistoRoboto.DeviceServer.Client import Client
from NistoRoboto.DeviceServer.OT2Client import OT2Client
from NistoRoboto.shared.utilities import listify


from math import ceil,sqrt
import json
import time
import requests
import shutil
import datetime


class OnePumpNICE_SampleProtocol:
    def __init__(self,
            load_url,
            prep_url,
            nice_url='NGBSANS.ncnr.nist.gov',
            camera_urls = None,
            snapshot_directory ='/home/nistoroboto/',
            ):

        if not (len(load_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on load_url')

        if not (len(prep_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on prep_url')

        self.app = None
        self.name = 'OnePumpNICE'

        #prepare samples
        self.prep_client = OT2Client(prep_url.split(':')[0],port=prep_url.split(':')[1])
        self.prep_client.login('SampleServer_PrepClient')
        self.prep_client.debug(False)
        
        #load samples
        self.load_client = Client(load_url.split(':')[0],port=load_url.split(':')[1])
        self.load_client.login('SampleServer_LoadClient')
        self.load_client.debug(False)

        self.init_nice(nice_url)

        self.camera_urls = camera_urls
        self.snapshot_directory = snapshot_directory

        self.cell_rinse_uuid = None
        self.catch_rinse_uuid = None

        self.default_nice_params ={
                'counter.countAgainst':'TIME',
                'groupid':'-1', 
                } 

        self.status_str = 'Fresh Server!'
        self.configurations = []
    def init_nice(self,nice_url):

        import nice
        self.nice_client = nice.connect(host=nice_url)

        #this MUST be imported after the nice_client connects
        from NistoRoboto.instrument.NICEDevice import NICEDevice
        self.nice_device = NICEDevice()
        self.nice_client.subscribe('devices',self.nice_device)

    def status(self):
        status = []
        for i,config in enumerate(self.configurations):
            status.append(f'{i}: {config}')
        status.append(f'Snapshots: {self.snapshot_directory}')
        status.append(f'Cameras: {self.camera_urls}')
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

            r = requests.get(cam_url,stream=True)
            if r.status_code == 200:
                with open(fname,'wb') as f:
                    r.raw.decode_content=True
                    shutil.copyfileobj(r.raw,f)

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
        elif kwargs['task_name']=='add_configuration':
            self.add_configuration(kwargs)
        elif kwargs['task_name']=='clear_configuration':
            del self.configurations[kwargs['configuration_index']]
        elif kwargs['task_name']=='clear_configurations':
            self.configurations = []
        else:
            raise ValueError(f'Task_name not recognized: {kwargs["task_name"]}')

    def add_configuration(self,kwargs):
        config = kwargs['configuration']
        runGroup = kwargs.get('runGroup',10)
        prefix = kwargs.get('prefix','ROBOT')
        user = kwargs.get('user','NGB')

        #get current state of NICE instrument
        nice_configs = self.nice_device.nodes['configuration.map'].currentValue.userVal.val
        if config['configuration'] not in nice_configs:
            raise ValueError(f'Configuration not found on instrument!\nRequested:{config["configuration"]}\nAvailable:{nice_configs.keys()}\n')

        self.configurations.append([config,runGroup,prefix,user])

    def measure(self,sample):
        for config_index in sample['configuration_indices']:
            config,runGroup,prefix,user = self.configurations[config_index]

            nice_params = self.default_nice_params.copy()
            nice_params.update(config)
            nice_params['sample.description'] = sample['name'] + ' ' + config['configuration']
            params_str = json.dumps(nice_params).replace(':','=')

            self.nice_client.console(f'runPoint {params_str} -g {runGroup} -p \"{prefix}\" -u \"{user}\"')

    def process_sample(self,sample):
        name = sample['name']

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
            time.sleep(10)
            self.take_snapshot(prefix = f'cleaned-{name}')
            self.update_status(f'Cell rinse done!')
        
        self.update_status(f'Loading sample into cell...')
        self.load_uuid = self.load_client.enqueue(task_name='loadSample',sampleVolume=sample['volume'])
        self.load_client.wait(self.load_uuid)
        time.sleep(10)
        take_image(prefix = f'loaded-{name}')
        
        self.update_status(f'Queueing catch rinse')
        self.catch_rinse_uuid = self.load_client.enqueue(task_name='rinseCatch')

        self.update_status(f'Asking NICE to measure sample {name}')
        self.measure(sample)
        self.update_status(f'Waiting for NICE to measure scattering of {name}')
        time.sleep(60)
        while str(self.nice_client.queue.queue_state) != 'IDLE':
            time.sleep(10)
            
        self.update_status(f'Cleaning up sample {name}')
        self.load_client.enqueue(task_name='rinseCell')
        self.cell_rinse_uuid = self.load_client.enqueue(task_name='blowOutCell')
        
        self.update_status(f'All done for {name}')
   






   
