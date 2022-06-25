from AFL.automation.APIServer.client.Client import Client
from AFL.automation.APIServer.client.OT2Client import OT2Client
from AFL.automation.shared.utilities import listify
from AFL.automation.APIServer.driver.Driver import Driver
from AFL.automation.agent.Serialize import serialize,deserialize
from AFL.automation.agent.AgentClient import AgentClient
from AFL.automation.shared.units import units

import pandas as pd
import numpy as np

from math import ceil,sqrt
import json
import time
import requests
import shutil
import datetime
import traceback
import pathlib
import uuid

import AFL.automation.prepare
import shutil
import h5py


class SAS_AL_SampleDriver(Driver):
    defaults={}
    defaults['snapshot_directory'] = '/home/nistoroboto'
    defaults['data_path'] = '/nfs/aux/chess/reduced_data/cycles/2022-1/id3b/beaucage-2324-D/analysis/'
    defaults['data_manifest_file'] = '/nfs/aux/chess/reduced_data/cycles/2022-1/id3b/beaucage-2324-D/analysis/data_manifest.csv'
    defaults['data_tag'] = 'default'
    def __init__(self,
            load_url,
            prep_url,
            sas_url,
            agent_url,
            camera_urls = None,
            snapshot_directory =None,
            overrides=None, 
            dummy_mode=False,
            ):

        Driver.__init__(self,name='SAS_AL_SampleDriver',defaults=self.gather_defaults(),overrides=overrides)

        if not (len(load_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on load_url')

        if not (len(prep_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on prep_url')

        if not (len(agent_url.split(':'))==2):
            raise ArgumentError('Need to specify both ip and port on agent_url')

        self.app = None
        self.name = 'SAS_AL_SampleDriver'

        self.dummy_mode= dummy_mode
        if not self.dummy_mode:
            #prepare samples
            self.prep_url = prep_url
            self.prep_client = OT2Client(prep_url.split(':')[0],port=prep_url.split(':')[1])
            self.prep_client.login('SampleServer_PrepClient')
            self.prep_client.debug(False)
            
            #load samples
            self.load_client = Client(load_url.split(':')[0],port=load_url.split(':')[1])
            self.load_client.login('SampleServer_LoadClient')
            self.load_client.debug(False)
    # 
            #load samples
            self.sas_url = sas_url
            self.sas_client = Client(sas_url.split(':')[0],port=sas_url.split(':')[1])
            self.sas_client.login('SampleServer_SASClient')
            self.sas_client.debug(False)
        else:
            self.sas_url = sas_url
            self.prep_url = prep_url
        
        #agent
        self.agent_url = agent_url
        self.agent_client = AgentClient(agent_url.split(':')[0],port=agent_url.split(':')[1])
        self.agent_client.login('SampleServer_AgentClient')
        self.agent_client.debug(False)

        self.camera_urls = camera_urls

        if snapshot_directory is not None:
            self.config['snapshot_directory'] = snapshot_directory

        self.rinse_uuid = None
        self.prep_uuid = None
        self.catch_uuid = None
        self.agent_uuid = None

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0 #seconds
        
        
        self.catch_protocol=None
        self.AL_status_str = ''
        self.data_manifest  = None
        self.AL_components = None
        
        self.reset_deck()
       
    def reset_deck(self):
        self.deck = AFL.automation.prepare.Deck()
        
    def add_container(self,name,slot):
        self.deck.add_container(name,slot)
        
    def add_catch(self,name,slot):
        self.deck.add_catch(name,slot)
        self.catch_loc=f"{slot}A1"
    
    def add_pipette(self,name,mount,tipracks):
        self.deck.add_pipette(name,mount,tipracks=tipracks)
        
    def send_deck_config(self,home=True):
        self.deck.init_remote_connection(
            self.prep_url.split(":")[0],
            home=home
        )
        self.deck.send_deck_config()
        
    def add_stock(self,stock_dict,loc):
        soln = AFL.automation.prepare.Solution.from_dict(stock_dict)
        self.deck.add_stock(soln,loc)
       
    def status(self):
        status = []
        status.append(f'Snapshots: {self.config["snapshot_directory"]}')
        status.append(f'Cameras: {self.camera_urls}')
        status.append(f'SAS: {self.sas_url}')
        status.append(f'Sample Wait Time: {self.wait_time}')
        status.append(f'AL_components: {self.AL_components}')
        status.append(f'{len(self.deck.stocks)} stocks loaded!')
        status.append(self.status_str)
        status.append(self.AL_status_str)
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

    def measure(self,sample):
        exposure = sample.get('exposure',None)

        sas_uuid = self.sas_client.enqueue(task_name='expose',name=sample['name'],block=True,exposure=exposure)
        self.sas_client.wait(sas_uuid)

        return sas_uuid

    #def execute(self,**kwargs):
    #    if self.app is not None:
    #        self.app.logger.debug(f'Executing task {kwargs}')
#
    #    if kwargs['task_name']=='sample':
    #        self.process_sample(kwargs)
    #    elif kwargs['task_name']=='measure':
    #        self.measure(kwargs)
    #    elif kwargs['task_name']=='take_snapshot':
    #        self.take_snapshot(kwargs['prefix'])
    #    elif kwargs['task_name']=='set_snapshot_directory':
    #        self.config['snapshot_directory'] = kwargs['snapshot_directory']
    #    elif kwargs['task_name']=='set_wait_time':
    #        self.wait_time = kwargs['wait_time']
    #    else:
    #        raise ValueError(f'Task_name not recognized: {kwargs["task_name"]}')

    def sample(self,sample):
        return self.process_sample(sample)
        
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
        empty = {}
        empty['name'] = 'MT-'+sample['name']
        empty['exposure'] = sample['exposure']
        empty['wiggle'] = False
        self.sas_uuid = self.measure(empty)
        self.sas_client.wait(self.sas_uuid)
            
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
        self.sas_uuid = self.measure(sample)

        self.update_status(f'Cleaning up sample {name}...')
        self.rinse_uuid = self.load_client.enqueue(task_name='rinseCell')

        self.update_status(f'Waiting for instrument to measure scattering of {name} with UUID {self.sas_uuid}...')
        self.sas_client.wait(self.sas_uuid)
        self.take_snapshot(prefix = f'06-after-measure-{name}')
            
        self.update_status(f'All done for {name}!')
        
    @Driver.unqueued()
    def stop_active_learning(self):
        self.stop_AL = True
        
    def set_catch_protocol(self,**kwargs): 
        self.catch_protocol = AFL.automation.prepare.PipetteAction(**kwargs)
    
    def active_learning_loop(self,**kwargs):
        self.AL_components = kwargs['AL_components']
        sample_volume = kwargs['sample_volume']
        exposure = kwargs['exposure']
        mix_order = kwargs['mix_order']
        custom_stock_settings = kwargs['custom_stock_settings']
        data_manifest_path = pathlib.Path(self.config['data_manifest_file'])
        data_path = pathlib.Path(self.config['data_path'])
        
        if self.dummy_mode:
            from AFL.automation.agent import PhaseMap
            df_measurements = pd.read_csv('/Users/tbm/projects/2001-NistoRoboto/2022-02-13-CodeDev/measurements.csv')
            
        self.stop_AL = False
        while not self.stop_AL:
            self.app.logger.info(f'Starting new AL loop')
            
            #get prediction of next step
            next_sample = self.agent_client.get_next_sample_queued()
            next_sample_dict = next_sample.T.squeeze().to_dict()
            self.app.logger.info(f'Preparing to make next sample: {next_sample_dict}')
            
            if self.dummy_mode:
                print(f'Pulling from {df_measurements.shape}')
                xy_all = PhaseMap.ternary2cart(df_measurements[self.AL_components].values)
                xy_next = PhaseMap.ternary2cart(next_sample[self.AL_components])
                dist = np.sqrt(np.sum(np.square(xy_all-xy_next),axis=1))
                argmin = np.argmin(dist)
                next_sample_full = df_measurements.iloc[argmin]
                next_sample = next_sample_full[self.AL_components].to_frame().T
                df_measurements = df_measurements.drop(argmin).reset_index(drop=True)
                print('\n\n\n')
                print(next_sample_full)
                print(df_measurements)
                print('\n\n\n')
                
            #make target object
            target = AFL.automation.prepare.Solution('target',list(next_sample.columns.values) + ['F127'])
            # target = AFL.automation.prepare.Solution('target',list(next_sample.columns.values))
            # target = AFL.automation.prepare.Solution('target',list(next_sample.columns.values) + ['NaCl'])
            target.mass_fraction = next_sample_dict
            target.volume = sample_volume*units('ul')
            # target.concentration = {'NaCl':110*units('mg/ml')}
            target.concentration = {'F127':100*units('mg/ml')}
            self.app.logger.info('Setting fixed F127 concentration of 100 mg/ml')
                
            self.deck.reset_targets()
            self.deck.add_target(target,name='target')
            self.deck.make_sample_series(reset_sample_series=True)
            self.deck.validate_sample_series(tolerance=0.15)
            self.deck.make_protocol(only_validated=False)
            self.fix_protocol_order(mix_order,custom_stock_settings)
            sample,validated = self.deck.sample_series[0]
            self.app.logger.info(self.deck.validation_report)
            
            if validated:
                self.app.logger.info(f'Validation PASSED')
                self.AL_status_str = 'Last sample validation PASSED'
            else:
                self.app.logger.info(f'Validation FAILED')
                self.AL_status_str = 'Last sample validation FAILED'
            self.app.logger.info(f'Making next sample with mass fraction: {sample.target_check.mass_fraction}')
            
            self.catch_protocol.source = sample.target_loc
            
            if self.dummy_mode:
                sample_name = next_sample_full['fname'].replace('_r1d','')
                sample.target_check.mass_fraction
                sample.target_check.mass_fraction = next_sample_dict
                sample.target_check.volume = sample_volume*units('ul')
                print('SAMPLE_NAME:',sample_name)
                time.sleep(5)
            else:
                sample_uuid = str(uuid.uuid4())
                sample_name = f'AL_{self.config["data_tag"]}_{sample_uuid}'
                self.process_sample(
                        dict(
                            name=sample_name,
                            prep_protocol = sample.emit_protocol(),
                            catch_protocol =[self.catch_protocol.emit_protocol()],
                            volume = self.catch_protocol.volume/1000.0,
                            exposure = exposure
                    )
                )
        

            # CHECK TRANMISSION OF LAST SAMPLE
            h5_path = data_path / (sample_name+'.h5')
            with h5py.File(h5_path,'r') as h5:
                transmission = h5['entry/sample/transmission'][()]

            if transmission>0.9:
                self.update_status(f'Last sample missed! (Transmission={transmission})')
                self.app.logger.info('Dropping this sample from AL and hoping the next one hits...')
                continue
            else:
                self.update_status(f'Last Sample success! (Transmission={transmission})')
            
            # update manifest
            if data_manifest_path.exists():
                self.data_manifest = pd.read_csv(data_manifest_path)
            else:
                self.data_manifest = pd.DataFrame(columns=['fname','label',*self.AL_components])
            
            row = {}
            row['fname'] = data_path/(sample_name+'_chosen_r1d.csv')
            row['label'] = -1
            total = 0
            for component in self.AL_components:
                m = sample.target_check.mass_fraction[component].magnitude
                row[component] = m
                total+=m
            for component in self.AL_components:
                row[component] = 100.0*(row[component]/total)
            
            self.data_manifest = self.data_manifest.append(row,ignore_index=True)
            self.data_manifest.to_csv(data_manifest_path,index=False)
            
            # trigger AL
            self.agent_uuid = self.agent_client.enqueue(task_name='update_phasemap',predict=True)
            
            # wait for AL
            self.app.logger.info(f'Waiting for agent...')
            self.agent_client.wait(self.agent_uuid)
            
            
    def fix_protocol_order(self,mix_order,custom_stock_settings):
        mix_order = [self.deck.get_stock(i) for i in mix_order]
        mix_order_map = {loc:new_index for new_index,(stock,loc) in enumerate(mix_order)}
        for sample,validated in self.deck.sample_series:
            # if not validated:
            #     continue
            old_protocol = sample.protocol
            ordered_indices = list(map(lambda x: mix_order_map.get(x.source),sample.protocol))
            argsort = np.argsort(ordered_indices)
            new_protocol = list(map(sample.protocol.__getitem__,argsort))
            time_patched_protocol = []
            for entry in new_protocol:
                if entry.source in custom_stock_settings:
                    for setting,value in custom_stock_settings[entry.source].items():
                        entry.__setattr__(setting,value)
                time_patched_protocol.append(entry)
            sample.protocol = time_patched_protocol
      
   






   
