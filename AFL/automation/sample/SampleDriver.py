import copy
import datetime
import os
import pathlib
import shutil
import traceback
import uuid
from typing import Optional, Dict, List

import h5py
import numpy as np
import pandas as pd
import requests
import xarray as xr
from tiled.client import from_uri

import AFL.automation.prepare
from AFL.automation.APIServer.Client import Client
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.units import units


class SampleDriver(Driver):
    """

    PersistentConfig Values
    -----------------------
    client: dict
        Contains APIServer uris (url:port) where the keys will be used as the accessor names.

    instrument: dict
        Description and execution/access/location information of each instrument to be used

    ternary: bool
        If true, process coordinates as ternary, Barycentric values

    data_tag: str
        Label for current measurements or active learning run
    """

    defaults = {}
    defaults['client'] = {}
    defaults['instrument'] = {}
    defaults['ternary'] = False
    defaults['data_tag'] = 'default'
    defaults['components'] = []
    defaults['AL_components'] = []
    defaults['csv_data_path'] = './'
    defaults['snapshot_directory'] = '/home/nistoroboto'
    defaults['max_sample_transmission'] = 0.6
    defaults['mix_order'] = []
    defaults['custom_stock_settings'] = []

    def __init__(
            self,
            tiled_uri: str,
            camera_urls: Optional[List[str]] = None,
            snapshot_directory: Optional[str] = None,
            overrides: Optional[Dict] = None,
    ):
        """

        Parameters
        -----------
        tiled_uri: str
            uri (url:port) of the tiled server

        camera_urls: Optional[List[str]]
            url endpoints for ip cameras


        """

        Driver.__init__(self, name='SampleDriver', defaults=self.gather_defaults(), overrides=overrides)

        self.deck = None
        self.sample_name: Optional[str] = None
        self.app = None
        self.name = 'SampleDriver'


        # start tiled catalog connection
        self.tiled_cat = from_uri(tiled_uri, api_key=os.environ['TILED_API_KEY'])

        self.camera_urls = camera_urls

        if snapshot_directory is not None:
            self.config['snapshot_directory'] = snapshot_directory

        #initialize client dict
        self.client = {}
        self.uuid = {'rinse': None, 'prep': None, 'catch': None, 'agent': None}

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0  # seconds

        self.catch_protocol = None
        self.AL_status_str = ''
        self.data_manifest = None

        # XXX need to make deck inside this object because of 'different registries error in Pint
        self.reset_deck()

    def status(self):
        status = []
        status.append(f'Snapshots: {self.config["snapshot_directory"]}')
        status.append(f'Cameras: {self.camera_urls}')
        status.append(f'{len(self.deck.stocks)} stocks loaded!')
        status.append(self.status_str)
        status.append(self.AL_status_str)
        return status

    def update_status(self, value):
        self.status_str = value
        self.app.logger.info(value)

    def get_client(self,name,refresh=False):
        try:
            client = self.client[name]
        except KeyError:
            if name not in self.config['client']:
                raise ValueError((
                    f"""Could not find client url for '{name}' in config. Current client dict in config is """
                    f"""self.config['client'] = {self.config['client']}"""
                ))
            url = self.config['client'][name]
            client = Client(url.split(':')[0], port=url.split(':')[1])
            self.client[name] = client
            refresh = True

        if refresh:
            client.login("SampleServer")
            client.debug(False)

        return client

    def take_snapshot(self, prefix):
        now = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
        for i, cam_url in enumerate(self.camera_urls):
            fname = self.config['snapshot_directory'] + '/'
            fname += prefix
            fname += f'-{i}-'
            fname += now
            fname += '.jpg'

            try:
                r = requests.get(cam_url, stream=True)
                if r.status_code == 200:
                    with open(fname, 'wb') as f:
                        r.raw.decode_content = True
                        shutil.copyfileobj(r.raw, f)
            except Exception as error:
                output_str = f'take_snapshot failed with error: {error.__repr__()}\n\n' + traceback.format_exc() + '\n\n'
                self.app.logger.warning(output_str)

    ########################
    ## DECK CONFIGURATION ##
    ########################
    def reset_deck(self):
        self.deck = AFL.automation.prepare.Deck()

    def add_container(self, name, slot):
        self.deck.add_container(name, slot)

    def add_catch(self, name, slot):
        self.deck.add_catch(name, slot)
        self.catch_loc = f"{slot}A1"

    def add_pipette(self, name, mount, tipracks):
        self.deck.add_pipette(name, mount, tipracks=tipracks)

    def send_deck_config(self, home=True):
        self.deck.init_remote_connection(
            self.get_client('prep').ip,
            home=home
        )
        self.deck.send_deck_config()

    def add_stock(self, stock_dict, loc):
        soln = AFL.automation.prepare.Solution.from_dict(stock_dict)
        self.deck.add_stock(soln, loc)


    def set_catch_protocol(self, **kwargs):
        self.catch_protocol = AFL.automation.prepare.PipetteAction(**kwargs)

    def fix_protocol_order(self, mix_order: List, custom_stock_settings: List):
        mix_order = [self.deck.get_stock(i) for i in mix_order]
        mix_order_map = {loc: new_index for new_index, (stock, loc) in enumerate(mix_order)}
        for sample, validated in self.deck.sample_series:
            # if not validated:
            #     continue
            old_protocol = sample.protocol
            ordered_indices = list(map(lambda x: mix_order_map.get(x.source), sample.protocol))
            argsort = np.argsort(ordered_indices)
            new_protocol = list(map(sample.protocol.__getitem__, argsort))
            time_patched_protocol = []
            for entry in new_protocol:
                if entry.source in custom_stock_settings:
                    for setting, value in custom_stock_settings[entry.source].items():
                        entry.__setattr__(setting, value)
                time_patched_protocol.append(entry)
            sample.protocol = time_patched_protocol

    def mfrac_to_mass(self, mass_fractions:Dict, fixed_conc: Dict, sample_volume, output_units:str='mg'):
        """Convert ternary/Barycentric mass fractions to mass"""
        if not (len(mass_fractions) == 3):
            raise ValueError('Only ternaries are currently supported. Need to pass three mass fractions')

        if len(fixed_conc) > 1:
            raise ValueError('Only one concentration should be fixed!')
        specified_component = list(fixed_conc.keys())[0]

        components = list(mass_fractions.keys())
        components.remove(specified_component)

        xB = mass_fractions[components[0]] * units('')
        xC = mass_fractions[components[1]] * units('')
        XB = xB / (1 - xB)
        XC = xC / (1 - xC)

        mA = (fixed_conc[specified_component] * sample_volume)
        mC = mA * (XC + XB * XC) / (1 - XB * XC)
        mB = XB * (mA + mC)

        mass_dict = {}
        mass_dict[specified_component] = mA.to(output_units)
        mass_dict[components[0]] = mB.to(output_units)
        mass_dict[components[1]] = mC.to(output_units)
        return mass_dict

    def process_sample(
            self,
            composition: Dict,
            sample_volume: Dict,
            fixed_concs: Dict,
            predict_next: bool = False,
            enqueue_next: bool = False,
            name: Optional[str] = None,
            uid: Optional[str] = None,
    ):
        """
        Parameters
        ----------

        composition: Dict
            Dict should be of the form composition["component_name"] = {"value":value, "units":units}

        sample_volume: dict
            Dict should be of the form sample_volume =  {"value":value, "units":units}

        fixed_concs: List[Optional[Dict]]
            Dict should be of the form fixed_concs[0] = {"value":value, "units":units}

        predict_next: bool
            If True, will trigger predict call to the agent

        enqueue_next: bool
            If True, will pull the next sample from the dropbox of the agent

        name: str
            The name of the sample, if not generated, it will be auto generated from the self.config['data_tag'] and
            uuid

        uid: str
            uuid of sample, if not specified it will be auto-generated
        """

        assert len(self.config['instrument'])>0, (
            """No instruments loaded in config for this server! Use client.set_config(instrument=[xyz])"""
        )
        assert ('load' in self.config['client']), (
            f"No client url for 'load'! self.config['client']={self.config['client']}"
        )
        assert ('prep' in self.config['client']), (
            f"No client url for 'prep'! self.config['client']={self.config['client']}"
        )
        if predict_next or enqueue_next:
            assert ('agent' in self.config['client']), (
                f"No client url for 'agent'! self.config['client']={self.config['client']}"
            )

        if uid is None:
            self.uuid['sample'] =  'SAM-' + str(uuid.uuid4())
        else:
            self.uuid['sample'] = uid

        if name is None:
            self.sample_name = f"{self.config['data_tag']}-{self.uuid['sample'][-8:]}"
        else:
            self.sample_name = None

        prep_protocol = self.compute_prep_protocol(
            composition = composition,
            fixed_concs = fixed_concs,
            sample_volume = sample_volume
        )

        # configure all servers to this sample name and uuid
        sample_data = self.set_sample(sample_name=self.sample_name, sample_uuid=self.uuid['sample'])
        for name, client in self.client.items():
            client.enqueue(task_name='set_sample', **sample_data)

        self.make_and_measure(name=name, prep_protocol=prep_protocol, catch_protocol=self.catch_protocol)

        if predict_next:
            self.predict_next_sample()

        # Look away ... here be dragons ...
        if enqueue_next:
            next_sample = self.get_client('agent').retrieve_obj(uid=self.uuid['AL'])
            next_sample_dict = {
                k: {'value': v, 'units': next_sample.attrs[k + '_units']} for k, v in next_sample.items()
            }

            task = {
                'task_name':'process_sample',
                'composition': next_sample_dict,
                'sample_volume': sample_volume,
                'fixed_concs':fixed_concs,
                'predict_next':predict_next,
                'enqueue_next':enqueue_next,
            }

            package = {
                'task':task,
                'meta':datetime.datetime.now().strftime('%m/%d/%y %H:%M:%S-%f'),
                'uuid': 'QD-' + str(uuid.uuid4())
            }
            queue_loc = self.app.task_queue.qsize() #append at end of queue
            self.app.task_queue.put(package,queue_loc)

    def compute_prep_protocol(self,composition: Dict, sample_volume: Dict, fixed_concs: Dict):
        """
        Parameters
        ----------
        composition: Dict
            Dict should be of the form composition["component_name"] = {"value":value, "units":units}

        sample_volume: Dict
            Dict should be of the form sample_volume =  {"value":value, "units":units}

        """

        sample_volume = sample_volume['value'] * units(sample_volume['units'])

        if self.config['ternary']:
            assert len(composition)==3, (
                f"Number of composition variables should be 3! You have composition = {composition}"
            )

            fixed_concs_units = {}
            for name, value in fixed_concs.items():
                fixed_concs_units[name] = value['value'] * units(value['units'])

            mass_dict = self.mfrac_to_mass(
                mass_fractions=composition,
                fixed_conc=fixed_concs_units,
                sample_volume=sample_volume,
                output_units='mg'
            )
        else:
            # assume concs for now...
            if len(composition) < (len(self.config['components']) - 1):
                raise ValueError('System under specified...')

            mass_dict = {}
            for name, comp in composition.items():
                mass_dict[name] = (comp['value'] * units(comp['units']) * sample_volume).to('mg')

        self.target = AFL.automation.prepare.Solution('target', self.config['components'])
        self.target.volume = sample_volume
        for k, v in mass_dict.items():
            self.target[k].mass = v
        self.target.volume = sample_volume

        ######################
        ## MAKE NEXT SAMPLE ##
        ######################
        self.deck.reset_targets()
        self.deck.add_target(self.target, name='target')
        self.deck.make_sample_series(reset_sample_series=True)
        self.deck.validate_sample_series(tolerance=0.15)
        self.deck.make_protocol(only_validated=False)
        self.fix_protocol_order(self.config['mix_order'], self.config['custom_stock_settings'])
        self.sample, self.validated = self.deck.sample_series[0]
        self.app.logger.info(self.deck.validation_report)

        if self.validated:
            self.app.logger.info(f'Validation PASSED')
            self.AL_status_str = 'Last sample validation PASSED'
        else:
            self.app.logger.info(f'Validation FAILED')
            self.AL_status_str = 'Last sample validation FAILED'
        self.app.logger.info(f'Making next sample with mass fraction: {self.sample.target_check.mass_fraction}')

        self.catch_protocol.source = self.sample.target_loc



    def make_and_measure(
            self,
            name: str,
            prep_protocol: dict,
            catch_protocol: dict,
    ):

        targets = set()
        for task in prep_protocol:
            if 'target' in task['source'].lower():
                targets.add(task['source'])
            if 'target' in task['dest'].lower():
                targets.add(task['dest'])

        for task in catch_protocol:
            if 'target' in task['source'].lower():
                targets.add(task['source'])
            if 'target' in task['dest'].lower():
                targets.add(task['dest'])

        target_map = {}
        for t in targets:
            prep_target = self.get_client('prep').enqueue(task_name='get_prep_target', interactive=True)['return_val']
            target_map[t] = prep_target

        for i, task in enumerate(prep_protocol):
            # if the well isn't in the map, just use the well
            task['source'] = target_map.get(task['source'], task['source'])
            task['dest'] = target_map.get(task['dest'], task['dest'])
            if i == 0:
                task['force_new_tip'] = True
            if i == (len(prep_protocol) - 1):  # last prepare
                task['drop_tip'] = False
            self.uuid['prep'] = self.get_client('prep').transfer(**task)

        if self.uuid['rinse'] is not None:
            self.update_status(f'Waiting for rinse...')
            self.get_client('load').wait(self.uuid['rinse'])
            self.update_status(f'Rinse done!')

        # calibrate sensor to avoid drift
        self.get_client('load').enqueue(task_name='calibrate_sensor')

        #XXX need to work out measure loop
        self.update_status(f'Cell is clean, measuring empty cell scattering...')
        self.measure(name=name, empty=True,wait=True)

        if self.uuid['prep'] is not None:
            self.get_client('prep').wait(self.uuid['prep'])
            self.take_snapshot(prefix=f'02-after-prep-{name}')

        self.update_status(f'Queueing sample {name} load into syringe loader')
        for task in self.catch_protocol:
            # if the well isn't in the map, just use the well
            task['source'] = target_map.get(task['source'], task['source'])
            task['dest'] = target_map.get(task['dest'], task['dest'])
            self.uuid['catch'] = self.get_client('prep').transfer(**task)

        if self.uuid['catch'] is not None:
            self.update_status(f"Waiting for sample prep/catch of {name} to finish: {self.uuid['catch'][-8:]}")
            self.get_client('prep').wait(self.uuid['catch'])
            self.take_snapshot(prefix=f'03-after-catch-{name}')

        # homing robot to try to mitigate drift problems
        self.get_client('prep').enqueue(task_name='home')

        # do the sample measurement train
        self.measure(name=name, empty=False, wait=True)

        self.update_status(f'Cleaning up sample {name}...')
        self.uuid['rinse'] = self.get_client('load').enqueue(task_name='rinseCell')
        self.take_snapshot(prefix=f'07-after-measure-{name}')

        self.update_status(f'All done for {name}!')


    def measure(self, name: str, empty: bool = False, wait: bool = True):
        # need to iterate over instrument dict
        #  - instrument dict will specify where to load sample to, how to call instrument, and any kwargs
        """
        instrument = dict (
            load_kw = {'load_dest_label':'AfterSANS'}
            client_name = 'larmor'
            measure_base_kw = {'task_name': expose, block:True, exposure: 3600}
            empty_base_kw = {'task_name': expose, block:True, exposure: 3600}
        )

        """
        assert len(self.config['instrument'])>0, 'No instruments loaded in config for this server!'

        if empty:
            name = 'MT-' + name

        instrument=None
        for i,instrument in enumerate(self.config['instrument']):
            if not empty:
                load_kw = {}
                if i==0:
                    load_kw['task_name'] = 'loadSample'
                else:
                    load_kw['task_name'] = 'advanceSample'
                load_kw['load_dest_label'] = instrument.get('load_dest_label','')
                self.uuid['load'] = self.get_client('load').enqueue(**load_kw)
                self.get_client('load').wait(self.uuid['load'])
                self.take_snapshot(prefix=f'05-after-load-{instrument["name"]}-{name}')

            if empty:
                measure_kw = instrument['measure_base_kw']
            else:
                measure_kw = instrument['empty_base_kw']
            measure_kw['name'] = name
            self.uuid['measure'] = self.get_client(instrument['client_name']).enqueue(**measure_kw)

        if wait:
            self.uuid['measure'] = self.get_client(instrument['client_name']).wait(self.uuid['measure'])
    def predict_next_sample(self):
        """Construct AL manifest from measurement and call predict"""
        data_path = pathlib.Path(self.config['data_path'])


        data_fname = self.sample_name + '_chosen_r1d.csv'
        measurement = pd.read_csv(
            data_path / data_fname,
            sep=',',
            comment='#',
            header=None,
            names=['q', 'I'],
            usecols=[0, 1]).set_index('q').squeeze().to_xarray().dropna('q')

        self.new_data = xr.Dataset()
        self.new_data['fname'] = data_fname
        self.new_data['SAS'] = measurement
        self.new_data['validated'] = self.validated
        #self.new_data['SAS_transmission'] = SAS_transmission
        self.new_data['sample_uuid'] = self.uuid['sample']

        sample_composition = {}
        if self.config['ternary']:
            total = 0
            for component in self.config['AL_components']:
                mf = self.sample.target_check.mass_fraction[component].magnitude
                self.new_data[component] = mf
                total += mf
            for component in self.config['AL_components']:
                self.new_data[component] = self.new_data[component] / total

                # for tiled
                sample_composition['ternary_mfrac_' + component] = self.sample.target_check.concentration[
                    component].to("mg/ml").magnitude
        else:
            for component in self.config['AL_components']:
                self.new_data[component] = self.sample.target_check.concentration[component].to("mg/ml").magnitude
                self.new_data[component].attrs['units'] = 'mg/ml'

                # for tiled
                sample_composition['conc_' + component] = self.sample.target_check.concentration[component].to(
                    "mg/ml").magnitude

        for component in self.config['components']:
            self.new_data['mfrac_' + component] = self.sample.target_check.mass_fraction[component].magnitude
            self.new_data['mass_' + component] = self.sample.target_check[component].mass.to('mg').magnitude
            self.new_data['mass_' + component].attrs['units'] = 'mg'

            # for tiled
            sample_composition['mfrac_' + component] = self.sample.target_check.mass_fraction[component].magnitude
            sample_composition['mass_' + component] = self.sample.target_check[component].mass.to('mg').magnitude

        self.new_data.to_netcdf(data_path / (self.sample_name + '.nc'))


        sample_composition['components'] = self.config['components']
        sample_composition['conc_units'] = 'mg/ml'
        sample_composition['mass_units'] = 'mg'
        if self.data is not None:
            self.data['sample_composition'] = sample_composition
            self.data['time'] = datetime.datetime.now().strftime('%m/%d/%y %H:%M:%S-%f %Z%z')
            self.data.finalize()


        self.uuid['AL'] = self.client['agent'].enqueue(task_name='predict',interactive=True)['return_val']

    def validate_measurements(self):
        data_path = self.config['data_path']
        h5_path = data_path / (self.sample_name + '.h5')
        with h5py.File(h5_path, 'r') as h5:
            self.SAS_transmission = h5['entry/sample/transmission'][()]

        if self.SAS_transmission > self.config['max_sample_transmission']:
            self.update_status(f'Last sample missed! (Transmission={self.SAS_transmission})')
            self.app.logger.info('Dropping this sample from AL and hoping the next one hits...')
            transmission_validated = False

        else:
            self.update_status(f'Last Sample success! (Transmission={self.SAS_transmission})')
            transmission_validated = True

        return transmission_validated