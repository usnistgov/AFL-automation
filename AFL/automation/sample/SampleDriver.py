import itertools
import datetime
import pathlib
import shutil
import traceback
import uuid
from typing import Optional, Dict, List
import warnings
import os
import time
import copy
import pandas as pd

import h5py  # type: ignore
import numpy as np
import requests  # type: ignore
import xarray as xr 
from tiled.client import from_uri  # type: ignore
from tiled.queries import Eq  # type: ignore
from scipy.spatial.distance import cdist

import AFL.automation.prepare  # type: ignore
from AFL.automation.APIServer.Client import Client  # type: ignore
from AFL.automation.APIServer.Driver import Driver  # type: ignore
from AFL.automation.shared.units import units  # type: ignore


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
    defaults['data_path'] = './'
    defaults['components'] = []
    defaults['AL_components'] = []
    defaults['snapshot_directory'] = str(pathlib.Path.home() / 'snaps')
    defaults['max_sample_transmission'] = 0.6
    defaults['mix_order'] = []
    defaults['custom_stock_settings'] = []
    defaults['composition_var_name'] = 'comps'
    defaults['concat_dim'] = 'sample'
    defaults['sample_composition_tol'] = 0.0
    defaults['next_samples_variable'] = 'next_samples'
    defaults['camera_urls'] = []
    defaults['grid_file'] = None
    defaults['grid_blank_interval'] = None
    defaults['grid_blank_sample'] = None

    def __init__(
            self,
            camera_urls: Optional[List[str]] = None,
            snapshot_directory: Optional[str] = None,
            overrides: Optional[Dict] = None,
    ):
        """

        Parameters
        -----------
        """

        Driver.__init__(self, name='SampleDriver', defaults=self.gather_defaults(), overrides=overrides)

        self.AL_campaign_name = None
        self.deck = None
        self.sample_name: Optional[str] = None
        self.app = None
        self.name = 'SampleDriver'

        if camera_urls is not None:
            self.config['camera_urls'] = camera_urls

        if snapshot_directory is not None:
            self.config['snapshot_directory'] = snapshot_directory

        #initialize client dict
        self.client = {}
        self.uuid = {'rinse': None, 'prep': None, 'catch': None, 'agent': None}

        self.status_str = 'Fresh Server!'
        self.wait_time = 30.0  # seconds

        self.catch_protocol = None
        self.AL_status_str = ''
        self.grid_sample_count = 0
        self.grid_data = None
        self.stop_grid = False

        # XXX need to make deck inside this object because of 'different registries error in Pint
        self.reset_deck()

    def validate_config(self):
        required_keys = [
            'client',
            'instrument',
            'ternary',
            'data_tag',
            'data_path',
            'components',
            'AL_components',
            'snapshot_directory',
            'max_sample_transmission',
            'mix_order',
            'custom_stock_settings',
            'composition_var_name',
            'concat_dim',
            'sample_composition_tol',
            'camera_urls'
        ]

        missing_keys = [key for key in required_keys if key not in self.config]

        if missing_keys:
            raise KeyError(f"The following required keys are missing from self.config: {', '.join(missing_keys)}")

        # Validate client configuration
        if not isinstance(self.config['client'], dict):
            raise TypeError("self.config['client'] must be a dictionary")
        if 'load' not in self.config['client']:
            raise KeyError("'load' client must be configured in self.config['client']")
        if 'prep' not in self.config['client']:
            raise KeyError("'prep' client must be configured in self.config['client']")

        # Validate instrument configuration
        if not isinstance(self.config['instrument'], list):
            raise TypeError("self.config['instrument'] must be a list")
        if len(self.config['instrument']) == 0:
            raise ValueError("At least one instrument must be configured in self.config['instrument']")

        for i, instrument in enumerate(self.config['instrument']):
            required_instrument_keys = ['name', 'client_name', 'data', 'measure_base_kw', 'empty_base_kw', 'sample_dim', 'sample_comps_variable']
            missing_instrument_keys = [key for key in required_instrument_keys if key not in instrument]
            if missing_instrument_keys:
                raise KeyError(f"Instrument {i} is missing the following required keys: {', '.join(missing_instrument_keys)}")
            
            if not isinstance(instrument['data'], list):
                raise TypeError(f"Instrument {i}: 'data' must be a list")
            for j, data_item in enumerate(instrument['data']):
                required_data_keys = ['data_name', 'tiled_array_name']
                missing_data_keys = [key for key in required_data_keys if key not in data_item]
                if missing_data_keys:
                    raise KeyError(f"Instrument {i}, data item {j} is missing the following required keys: {', '.join(missing_data_keys)}")

        # Validate other list types
        list_keys = ['components', 'AL_components', 'mix_order', 'camera_urls']
        for key in list_keys:
            if not isinstance(self.config[key], list):
                raise TypeError(f"self.config['{key}'] must be a list")
        # Validate dicts

        if not isinstance(self.config['custom_stock_settings'],dict):
            raise TypeError("self.config['custom_stock_settings'] must be a dict")

        # Validate other dict types
        list_keys = ['custom_stock_settings']
        for key in list_keys:
            if not isinstance(self.config[key], dict):
                raise TypeError(f"self.config['{key}'] must be a dict")

        # Validate types of other keys
        if not isinstance(self.config['ternary'], bool):
            raise TypeError("self.config['ternary'] must be a boolean")
        if not isinstance(self.config['data_tag'], str):
            raise TypeError("self.config['data_tag'] must be a string")
        if not isinstance(self.config['data_path'], (str, pathlib.Path)):
            raise TypeError("self.config['data_path'] must be a string or pathlib.Path")
        if not isinstance(self.config['snapshot_directory'], (str, pathlib.Path)):
            raise TypeError("self.config['snapshot_directory'] must be a string or pathlib.Path")
        if not isinstance(self.config['max_sample_transmission'], (int, float)):
            raise TypeError("self.config['max_sample_transmission'] must be a number")
        if not isinstance(self.config['composition_var_name'], str):
            raise TypeError("self.config['composition_var_name'] must be a string")
        if not isinstance(self.config['concat_dim'], str):
            raise TypeError("self.config['concat_dim'] must be a string")
        if not isinstance(self.config['sample_composition_tol'], (int, float)):
            raise TypeError("self.config['sample_composition_tol'] must be a number")

        print("Configuration validation passed successfully.")

    def validate_config_grid(self):
        """Validate configuration specific to grid-based sample processing."""
        # Basic client validation
        if not isinstance(self.config['client'], dict):
            raise TypeError("self.config['client'] must be a dictionary")
            
        # Instrument validation - simplified compared to regular validate_config
        if not isinstance(self.config['instrument'], list):
            raise TypeError("self.config['instrument'] must be a list")
        if len(self.config['instrument']) == 0:
            raise ValueError("At least one instrument must be configured in self.config['instrument']")
            
        for i, instrument in enumerate(self.config['instrument']):
            # Minimal required keys for grid mode
            required_instrument_keys = ['client_name', 'data', 'measure_base_kw', 'empty_base_kw']
            missing_instrument_keys = [key for key in required_instrument_keys if key not in instrument]
            if missing_instrument_keys:
                raise KeyError(f"Instrument {i} is missing the following required keys: {', '.join(missing_instrument_keys)}")
                
            if not isinstance(instrument['data'], list):
                raise TypeError(f"Instrument {i}: 'data' must be a list")
            for j, data_item in enumerate(instrument['data']):
                required_data_keys = ['data_name', 'tiled_array_name']
                missing_data_keys = [key for key in required_data_keys if key not in data_item]
                if missing_data_keys:
                    raise KeyError(f"Instrument {i}, data item {j} is missing the following required keys: {', '.join(missing_data_keys)}")
                    
        # Validate grid-specific configuration items
        if self.config['grid_file'] is not None and not isinstance(self.config['grid_file'], (str, pathlib.Path)):
            raise TypeError("self.config['grid_file'] must be a string or pathlib.Path")
            
        if self.config['grid_blank_interval'] is not None and not isinstance(self.config['grid_blank_interval'], int):
            raise TypeError("self.config['grid_blank_interval'] must be an integer")
            
        if self.config['grid_blank_sample'] is not None and not isinstance(self.config['grid_blank_sample'], dict):
            raise TypeError("self.config['grid_blank_sample'] must be a dictionary")
            
        # Validate data-related settings
        if not isinstance(self.config['data_path'], (str, pathlib.Path)):
            raise TypeError("self.config['data_path'] must be a string or pathlib.Path")
            
        if not isinstance(self.config['data_tag'], str):
            raise TypeError("self.config['data_tag'] must be a string")
            
        # Validate instrument configuration
        if not isinstance(self.config['instrument'], list):
            raise TypeError("self.config['instrument'] must be a list")
        if len(self.config['instrument']) == 0:
            raise ValueError("At least one instrument must be configured in self.config['instrument']")

        for i, instrument in enumerate(self.config['instrument']):
            required_instrument_keys = ['client_name', 'data', 'measure_base_kw', 'empty_base_kw', 'sample_dim', 'sample_comps_variable']
            missing_instrument_keys = [key for key in required_instrument_keys if key not in instrument]
            if missing_instrument_keys:
                raise KeyError(f"Instrument {i} is missing the following required keys: {', '.join(missing_instrument_keys)}")
            
            if not isinstance(instrument['data'], list):
                raise TypeError(f"Instrument {i}: 'data' must be a list")
            for j, data_item in enumerate(instrument['data']):
                required_data_keys = ['data_name', 'tiled_array_name']
                missing_data_keys = [key for key in required_data_keys if key not in data_item]
                if missing_data_keys:
                    raise KeyError(f"Instrument {i}, data item {j} is missing the following required keys: {', '.join(missing_data_keys)}")
            
        print("Grid configuration validation passed successfully.")

    @property
    def tiled_client(self):
        # start tiled catalog connection
        if self.data is None:
            raise ValueError("No DataTiled object added to this class...was it instantiated correctly?")
        return self.data.tiled_client

    def status(self):
        status = []
        status.append(f'Snapshots: {self.config["snapshot_directory"]}')
        status.append(f'Cameras: {self.config["camera_urls"]}')
        status.append(f'{len(self.deck.stocks)} stocks loaded!')
        status.append(self.status_str)
        status.append(self.AL_status_str)
        if self.grid_data:
            status.append(f'Grid Dims: {self.grid_data.sizes}')
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
        for i, cam_url in enumerate(self.config['camera_urls']):
            fname = pathlib.Path(self.config['snapshot_directory']) / (
                f"{prefix}-{i}-{now}.jpg"
            )

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

    def fix_protocol_order(self, mix_order: List, custom_stock_settings: Dict):
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
                        entry.kwargs[setting] = value
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
            prepare_mfrac_split: Optional[Dict]=None,
            predict_combine_comps: Optional[Dict]=None,
            predict_next: bool = False,
            enqueue_next: bool = False,
            calibrate_sensor: bool = False,
            name: Optional[str] = None,
            sample_uuid: Optional[str] = None,
            AL_campaign_name: Optional[str] = None,
            AL_uuid: Optional[str] = None,
    ):
        """Make protocol for, mix, load, and measure sample. Potentially query Agent for next sample and enqueue

        Parameters
        ----------

        composition: Dict
            Dict should be of the form composition["component_name"] = {"value":value, "units":units}

        sample_volume: dict
            Dict should be of the form sample_volume =  {"value":value, "units":units}

        fixed_concs: Optional[Dict]
            Dict should be of the form fixed_concs[component] = {"value":value, "units":units}

        mfrac_split: Dict
            Dict should be of the form mfrac_split = {'component_to_split':{'component_A':'mfrac_A','component_B':'mfrac_B'}}

        predict_next: bool
            If True, will trigger predict call to the agent

        enqueue_next: bool
            If True, will pull the next sample from the dropbox of the agent

        calibrate_sensor: bool
            If True, trigger a load stopper sensor recalibration before the next measurement

        name: str
            The name of the sample, if not generated, it will be auto generated from the self.config['data_tag'] and
            uuid

        sample_uuid: str
            uuid of sample, if not specified it will be auto-generated

        AL_uuid: str
            uuid of AL campaign

        AL_campaign_name: str
            name of AL campaign
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


        # do this now, so that we fail early if we're missing something
        self.validate_config()

        if sample_uuid is None:
            self.uuid['sample'] =  'SAM-' + str(uuid.uuid4())
        else:
            self.uuid['sample'] = sample_uuid

        if name is None:
            self.sample_name = f"{self.config['data_tag']}_{self.uuid['sample'][-8:]}"
        else:
            self.sample_name = name

        if predict_next and AL_uuid is None:
            self.uuid['AL'] = 'AL-' + str(uuid.uuid4())
        else:
            self.uuid['AL'] = AL_uuid

        if predict_next and AL_campaign_name is None:
            self.AL_campaign_name = f"{self.config['data_tag']}_{self.uuid['AL'][-8:]}"
        else:
            self.AL_campaign_name = AL_campaign_name
       

        print(f'Composition: {composition}')
        if composition: # composition is not empty
            prep_protocol, catch_protocol = self.compute_prep_protocol(
                composition = composition,
                fixed_concs = fixed_concs,
                mfrac_split = prepare_mfrac_split,
                sample_volume = sample_volume
            )

            # configure all servers to this sample name and uuid
            sample_composition_realized = {
                k:{'value':v.magnitude ,'units':str(v.units)} for k,v in self.sample.target_check.concentration.items()
            }
            self.data['sample_composition_target'] = composition
            self.data['sample_composition_realized'] = sample_composition_realized
            sample_data = self.set_sample(
                sample_name = self.sample_name,
                sample_uuid = self.uuid['sample'],
                AL_campaign_name = self.AL_campaign_name,
                AL_uuid = self.uuid['AL'],
                AL_components = self.config['AL_components'],
                sample_composition = sample_composition_realized,
            )
            for client_name in self.config['client'].keys():
                if client_name not in self.config['tiled_exclusion_list']:
                    self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)

            # START NEW INDENT 
            prep_protocol, catch_protocol = self.compute_prep_protocol(
                composition = composition,
                fixed_concs = fixed_concs,
                mfrac_split = prepare_mfrac_split,
                sample_volume = sample_volume
            )

            # configure all servers to this sample name and uuid
            sample_composition_realized = {
                k:{'value':v.magnitude ,'units':str(v.units)} for k,v in self.sample.target_check.concentration.items()
            }
            self.data['sample_composition_target'] = composition
            self.data['sample_composition_realized'] = sample_composition_realized
            sample_data = self.set_sample(
                sample_name = self.sample_name,
                sample_uuid = self.uuid['sample'],
                AL_campaign_name = self.AL_campaign_name,
                AL_uuid = self.uuid['AL'],
                AL_components = self.config['AL_components'],
                sample_composition = sample_composition_realized,
            )
            for client_name in self.config['client'].keys():
                if client_name not in self.config['tiled_exclusion_list']:
                    self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)

            self.make_and_measure(name=self.sample_name, prep_protocol=prep_protocol, catch_protocol=catch_protocol, calibrate_sensor=calibrate_sensor)
            self.construct_datasets(combine_comps=predict_combine_comps)
            # END NEW INDENT 

        if enqueue_next or predict_next:
            if composition:#assume we made/measured a sample and append
                self.add_new_data_to_agent()
            self.predict_next_sample()

        # Look away ... here be dragons ...
        if enqueue_next:
            ag_result = self.get_client('agent').retrieve_obj(uid=self.uuid['agent'])
            next_samples = ag_result[self.config['next_samples_variable']]
            
            new_composition = next_samples.to_pandas().squeeze().to_dict()
            new_composition = {k:{'value':v,'units':'milligram / milliliter'} for k,v in new_composition.items()}

            task = {
                'task_name':'process_sample',
                'composition': new_composition,
                'sample_volume': sample_volume,
                'fixed_concs':fixed_concs,
                'prepare_mfrac_split':prepare_mfrac_split,
                'predict_combine_comps': predict_combine_comps,
                'predict_next':predict_next,
                'enqueue_next':enqueue_next,
                'AL_campaign_name':self.AL_campaign_name,
                'AL_uuid': self.uuid['AL'],
            }

            task_uuid =  'QD-' + str(uuid.uuid4())
            package = {'task':task,'meta':{},'uuid':task_uuid}
            package['meta']['queued'] = datetime.datetime.now().strftime('%m/%d/%y %H:%M:%S-%f')

            queue_loc = self._queue.qsize() #append at end of queue
            self._queue.put(package,queue_loc)




    def compute_prep_protocol(self,composition: Dict, sample_volume: Dict, fixed_concs: Dict, mfrac_split:Optional[Dict]=None):
        """
        Parameters
        ----------
        composition: Dict
            Dict should be of the form composition["component_name"] = {"value":value, "units":units}

        sample_volume: Dict
            Dict should be of the form sample_volume =  {"value":value, "units":units}

        mfrac_split: Dict
            Dict should be of the form mfrac_split = {'component_to_split':{'component_A':'mfrac_A','component_B':'mfrac_B'}}

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
            if len(composition) < (len(self.config['components']) - len(fixed_concs) - 1):
                raise ValueError('System under specified...')

            mass_dict = {}
            for name, comp in composition.items():
                mass_dict[name] = (comp['value'] * units(comp['units']) * sample_volume).to('mg')

            for name, comp in fixed_concs.items():
                mass_dict[name] = (comp['value'] * units(comp['units']) * sample_volume).to('mg')

            print(mass_dict)

            if mfrac_split is not None:
                for split_component, split_def in mfrac_split.items():
                    target_mass = mass_dict[split_component]
                    for component,mfrac in split_def.items():
                        mass_dict[component] =  target_mass*mfrac
                    del mass_dict[split_component]


            # for component in self.config['components']:
            #     if component not in mass_dict:
            #         mass_dict[component] = 0.0*units('mg')


        self.target = AFL.automation.prepare.Solution('target', self.config['components'])
        #self.target = AFL.automation.prepare.Solution('target', list(composition.keys()))

        self.target.volume = sample_volume
        for k, v in mass_dict.items():
            self.target[k].mass = v
        self.target.volume = sample_volume

        self.deck.reset_targets()
        self.deck.add_target(self.target, name='target')
        self.deck.make_sample_series(reset_sample_series=True)
        self.deck.validate_sample_series(tolerance=self.config['sample_composition_tol'])
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

        self.protocol = self.sample.emit_protocol()

        return self.sample.emit_protocol(), [self.catch_protocol.emit_protocol()]


    def make_and_measure(
            self,
            name: str,
            prep_protocol: dict,
            catch_protocol: dict,
            calibrate_sensor: bool = False,
    ):
        self.update_status(f'starting make and measure for {name}')
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
                task['drop_tip'] = True# false to conserve tips, not working with OT2HTTP False
            self.uuid['prep'] = self.get_client('prep').enqueue(task_name='transfer',**task)

        if self.uuid['rinse'] is not None:
            self.update_status(f'Waiting for rinse...')
            self.get_client('load').wait(self.uuid['rinse'],for_history=False)
            self.update_status(f'Rinse done!')

        if calibrate_sensor:
                # calibrate sensor to avoid drift
                self.get_client('load').enqueue(task_name='calibrate_sensor')

        #XXX need to work out measure loop
        self.update_status(f'Cell is clean, measuring empty cell scattering...')
        self.measure(name=name, empty=True,wait=True)

        if self.uuid['prep'] is not None:
            self.get_client('prep').wait(self.uuid['prep'],for_history=False)
            self.take_snapshot(prefix=f'02-after-prep-{name}')

        self.update_status(f'Queueing sample {name} load into syringe loader')
        for task in catch_protocol:
            # if the well isn't in the map, just use the well
            task['source'] = target_map.get(task['source'], task['source'])
            task['dest'] = target_map.get(task['dest'], task['dest'])
            self.uuid['catch'] = self.get_client('prep').enqueue(task_name='transfer',**task)

        if self.uuid['catch'] is not None:
            self.update_status(f"Waiting for sample prep/catch of {name} to finish: {self.uuid['catch'][-8:]}")
            self.get_client('prep').wait(self.uuid['catch'])
            self.take_snapshot(prefix=f'03-after-catch-{name}')

        # homing robot to try to mitigate drift problems
        self.get_client('prep').enqueue(task_name='home')

        # do the sample measurement train
        self.update_status(f"Measuring sample with all loaded instruments...")
        self.measure(name=name, empty=False, wait=True)

        self.update_status(f'Cleaning up sample {name}...')
        self.uuid['rinse'] = self.get_client('load').enqueue(task_name='rinseCell')
        self.take_snapshot(prefix=f'07-after-measure-{name}')

        self.reset_sample_env(wait=False)

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
            self.update_status(f'Measuring using instrument #{i}')
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
                measure_kw = instrument['empty_base_kw']
            else:
                measure_kw = instrument['measure_base_kw']
            measure_kw['name'] = name
            
            if 'sample_env' in instrument.keys() and not empty:
                """
                  schema:
                    'sample_env': { 'client_name' = 'tempdeck',
                                    'move_base_kw' = {'task_name': 'move_temp'},
                                    'move_swept_kw' = {'temperature': [15,20,25,30]},
                                    }
                                    
                """
                params = []
                vals = []
                for param,conds in instrument['sample_env']['move_swept_kw'].items():
                    params.append(param)
                    vals.append(conds)
                conditions = [{i:j for i,j in zip(params,vallist)} for vallist in itertools.product(*vals)]
                # this ravels the list of conditions above in n-dimensional space, e.g.:
                # 'move_swept_kw' = {'temperature': [15,20,25,30], 'vibes': ['harsh', 'mid', 'cool']}
                # conditions = [{'temperature': 15, 'vibes': 'harsh'}, {'temperature': 15, 'vibes': 'mid'} ...]

                starting_condition = conditions[0]
                sample_data = self.get_sample()
                base_sample_name = sample_data["sample_name"]
                for i,cond in enumerate(conditions):
                    sample_env_kw = {}
                    sample_env_kw.update(cond)
                    sample_env_kw.update(instrument['sample_env']['move_base_kw'])
                    sample_data = self.get_sample()
                    sample_data['sample_env_conditions'] = cond
                    sample_data['sample_name'] = base_sample_name + f'_{str(i).zfill(3)}' # track up to 1000 conditions

                    self.get_client(instrument['sample_env']['client_name']).enqueue(task_name='set_sample',**sample_data)
                    self.get_client(instrument['client_name']).enqueue(task_name='set_sample',**sample_data)
                    self.update_status(f'Moving sample env {instrument["sample_env"]["client_name"]}...') 
                    self.uuid['move_sample_env'] = self.get_client(instrument['sample_env']['client_name']).enqueue(**sample_env_kw)
                    
                    self.get_client(instrument['sample_env']['client_name']).wait(self.uuid['move_sample_env'])
                    self.update_status(f'Measuring on instrument {instrument["client_name"]}')
                    measure_kw['name'] = sample_data['sample_name']
                    self.uuid['measure'] = self.get_client(instrument['client_name']).enqueue(**measure_kw)
                    
                    self.get_client(instrument['client_name']).wait(self.uuid['measure'])

                # # move sample environment to initial starting state to prepare for next measurement
                # sample_env_kw = {}
                # sample_env_kw.update(starting_condition)
                # sample_env_kw.update(instrument['sample_env']['move_base_kw'])
                # self.uuid['move_sample_env'] = self.get_client(instrument['sample_env']['client_name']).enqueue(**sample_env_kw)

            else:
                self.uuid['measure'] = self.get_client(instrument['client_name']).enqueue(**measure_kw)

                if wait:
                    self.get_client(instrument['client_name']).wait(self.uuid['measure'])

    def reset_sample_env(self, wait: bool = True):

        for i,instrument in enumerate(self.config['instrument']):
            if 'sample_env' in instrument.keys():
                """
                  schema:
                    'sample_env': { 'client_name' = 'tempdeck',
                                    'move_base_kw' = {'task_name': 'move_temp'},
                                    'move_swept_kw' = {'temperature': [15,20,25,30]},
                                    }
                                    
                """
                params = []
                vals = []
                for param,conds in instrument['sample_env']['move_swept_kw'].items():
                    params.append(param)
                    vals.append(conds)
                conditions = [{i:j for i,j in zip(params,vallist)} for vallist in itertools.product(*vals)]
                # this ravels the list of conditions above in n-dimensional space, e.g.:
                # 'move_swept_kw' = {'temperature': [15,20,25,30], 'vibes': ['harsh', 'mid', 'cool']}
                # conditions = [{'temperature': 15, 'vibes': 'harsh'}, {'temperature': 15, 'vibes': 'mid'} ...]

                starting_condition = conditions[0]

                sample_env_kw = {}
                sample_env_kw.update(starting_condition)
                sample_env_kw.update(instrument['sample_env']['move_base_kw'])
                self.uuid['move_sample_env'] = self.get_client(instrument['sample_env']['client_name']).enqueue(**sample_env_kw)

                if wait:
                    self.get_client(instrument['sample_env']['client_name']).wait(self.uuid['move_sample_env'])


    def construct_datasets(self,combine_comps=None):
        """Construct AL manifest from measurement and call predict"""
        data_path = pathlib.Path(self.config['data_path'])
        # if len(self.config['instrument'])>1:
        #     raise NotImplementedError

        if self.tiled_client is None:
            self.tiled_client = self.data.tiled_client
            # this needs to be here, because in the constructor, we don't have the datapacket attached

        self.new_data = xr.Dataset()
        for i, instrument in enumerate(self.config['instrument']):
            for instrument_data in instrument['data']:
                tiled_result = (
                    self.tiled_client
                    .search(Eq('sample_uuid', self.uuid['sample']))
                    .search(Eq('array_name', instrument_data['tiled_array_name']))
                )
                if len(tiled_result) == 0:
                    raise ValueError(f"Could not find tiled entry for measurement sample_uuid={self.uuid['sample']}")

                # handle Python None and "None" depending on how json deserialization works out
                if (instrument_data['data_dim'] is not None) and (instrument_data['data_dim'] != 'None'):
                    dims = instrument_data['data_dim']
                    coords = {instrument_data['data_dim']: tiled_result.items()[-1][-1].metadata[
                        instrument_data['tiled_metadata_dim']]}
                else:
                    dims = None
                    coords = None

                if 'sample_env' in instrument.keys():

                    sample_env_dims = list(instrument['sample_env']['move_swept_kw'].keys())

                    measurement_list = []
                    for _,tiled_data in tiled_result.items():
                        if 'MT-' in tiled_data.metadata['name']:
                            continue
                        measurement_list.append(xr.DataArray(tiled_data[()], dims=dims, coords=coords))
                    measurement = xr.concat(measurement_list, dim=instrument['sample_dim'])
                    for key,values in instrument['sample_env']['move_swept_kw'].items():
                        measurement[key] = (instrument['sample_dim'],values)
                    self.new_data[instrument_data['data_name']] = measurement
                    print(self.new_data)
                    print(self.new_data)
                else:

                    tiled_data = tiled_result.items()[-1][-1]
                    measurement = xr.DataArray(tiled_data[()], dims=dims, coords=coords)
                    self.new_data[instrument_data['data_name']] = measurement

                if 'quality_metric' in instrument.keys():
                    quality_metric = instrument['quality_metric']
                    instrument_value = tiled_data.metadata[quality_metric['tiled_metadata_key']]
                    if quality_metric['comparison'].lower() in ['<', 'lt']:
                        accept = instrument_value < quality_metric['threshold']
                    elif quality_metric['comparison'].lower() in ['>', 'gt']:
                        accept = instrument_value > quality_metric['threshold']
                    elif quality_metric['comparison'].lower() in ['==', '=', 'eq']:
                        accept = instrument_value == quality_metric['threshold']
                    else:
                        raise ValueError(
                            f'Cannot recognize comparison for quality_metric. You passed {quality_metric["comparison"]}')
                else:
                    accept = True
                self.new_data[instrument_data['data_name']].attrs['accept'] = int(accept)

        self.new_data['validated'] = self.validated
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
                try:
                    self.new_data[component] = self.sample.target_check.concentration[component].to("mg/ml").magnitude
                    self.new_data[component].attrs['units'] = 'mg/ml'

                    # for tiled
                    sample_composition['conc_' + component] = self.sample.target_check.concentration[component].to(
                    "mg/ml").magnitude
                except KeyError:
                    warnings.warn(f"Skipping component {component} in AL_components")

        for component in self.config['components']:
            self.new_data['mfrac_' + component] = self.sample.target_check.mass_fraction[component].magnitude
            self.new_data['mass_' + component] = self.sample.target_check[component].mass.to('mg').magnitude
            self.new_data['mass_' + component].attrs['units'] = 'mg'
            if self.sample.target_check[component].volume is not None:
                self.new_data['volume_' + component] = self.sample.target_check[component].volume.to('ml').magnitude
                self.new_data['volume_' + component].attrs['units'] = 'ml'

            # for tiled
            sample_composition['mfrac_' + component] = self.sample.target_check.mass_fraction[component].magnitude
            sample_composition['mass_' + component] = self.sample.target_check[component].mass.to('mg').magnitude

        if combine_comps is not None:
            for new_component,combine_list in combine_comps.items():
                conc = 0 * units('mg/ml')
                mass = 0 * units('mg')
                volume = 0 * units('ul')
                for component in combine_list:
                    conc += self.sample.target_check.concentration[component].to("mg/ml")
                    mass += self.sample.target_check[component].mass.to("mg")
                    volume += self.sample.target_check[component].volume.to("ul")

                self.new_data[new_component] = conc.to("mg/ml").magnitude #include as main AL variable
                self.new_data['conc_'+new_component] = conc.to("mg/ml").magnitude
                self.new_data['mass_'+new_component] = mass.to("mg").magnitude
                self.new_data['volume_'+new_component] = volume.to("ul").magnitude

        self.new_data.to_netcdf(data_path / (self.sample_name + '.nc'))

        sample_composition['components'] = self.config['components']
        sample_composition['conc_units'] = 'mg/ml'
        sample_composition['mass_units'] = 'mg'
        sample_composition = {str(k):v for k,v in sample_composition.items()}
        if self.data is not None:
            self.data['sample_composition'] = sample_composition
            self.data['time'] = datetime.datetime.now().strftime('%m/%d/%y %H:%M:%S-%f %Z%z')
            #self.data.finalize() #I don't think we want this with the new sampel_server style

    def add_new_data_to_agent(self,combine_comps=None):
        """Construct AL manifest from measurement and call predict"""

        for i,instrument in enumerate(self.config['instrument']):
            self.ds_append = xr.Dataset()
            self.ds_append[instrument['sample_comps_variable']] = self.new_data[self.config['AL_components']].to_array('component').transpose(...,'component')

            data_added=0
            for instrument_data in instrument['data']:
                if bool(self.new_data[instrument_data['data_name']].attrs['accept']):#because xArray and json is the worst
                    self.ds_append[instrument_data['data_name']] = self.new_data[instrument_data['data_name']]
                    data_added+=1
                else:
                    continue

            if data_added>0:
                self.ds_append = self.ds_append.reset_coords()
                if instrument['sample_dim'] not in self.ds_append:
                    self.ds_append = self.ds_append.expand_dims(instrument['sample_dim'])
                db_uuid = self.get_client('agent').deposit_obj(obj=self.ds_append)
                self.get_client('agent').enqueue(task_name='append',db_uuid=db_uuid,concat_dim=instrument['sample_dim'])

    def predict_next_sample(self):
        self.uuid['agent'] = self.get_client('agent').enqueue(
            task_name='predict',
            sample_uuid=self.uuid['sample'],
            AL_campaign_name=self.AL_campaign_name,
            interactive=True
        )['return_val']

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

    def process_sample_grid(
            self,
            sample,
            name: Optional[str] = None,
            sample_uuid: Optional[str] = None,
            AL_campaign_name: Optional[str] = None,
            AL_uuid: Optional[str] = None,
            predict_next: bool = False,
            enqueue_next: bool = False,
            reset_grid: bool = False,
    ):
        """Process a sample from a grid of samples.

        Parameters
        ----------
        sample: Dict, optional
            Dictionary containing sample coordinates or properties. If None, will be fetched 
            from the grid or agent.
            
        name: str, optional
            The name of the sample. If not provided, will be auto-generated.
            
        sample_uuid: str, optional
            UUID for the sample. If not provided, will be auto-generated.
            
        AL_campaign_name: str, optional
            Name of the active learning campaign.
            
        AL_uuid: str, optional
            UUID for the active learning campaign.
            
        predict_next: bool
            If True, triggers a predict call to the agent.
            
        enqueue_next: bool
            If True, will enqueue the next sample for measurement.
            
        """
        # Validate config for grid processing
        self.validate_config_grid()

        if reset_grid or self.grid_data is None:
            self.reset_grid()
        
        # Handle sample UUID generation
        if sample_uuid is None:
            self.uuid['sample'] = 'SAM-' + str(uuid.uuid4())
        else:
            self.uuid['sample'] = sample_uuid
            
        # Handle AL UUID
        if predict_next and AL_uuid is None:
            self.uuid['AL'] = 'AL-' + str(uuid.uuid4())
        else:
            self.uuid['AL'] = AL_uuid
            
        # Handle campaign name
        if predict_next and AL_campaign_name is None:
            self.AL_campaign_name = f"{self.config['data_tag']}_{self.uuid['AL'][-8:]}"
        else:
            self.AL_campaign_name = AL_campaign_name
        
        # Check if we should measure a blank
        if (self.config['grid_blank_interval'] is not None and 
            self.config['grid_blank_sample'] is not None and 
            self.grid_sample_count > 0 and 
            self.grid_sample_count % self.config['grid_blank_interval'] == 0):
            
            self.update_status(f"Measuring blank sample (scheduled interval {self.config['grid_blank_interval']})")
            blank_sample = self.config['grid_blank_sample']
            blank_name = f"blank_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Configure blank measurement
            self.measure_grid_sample(blank_sample, name=blank_name, empty=True)
            
        # Handle the next sample based on mode
        if sample is not None:
            # find the closest sample in the grid by euclidean distance
            available = self.grid_data[self.config['components']].to_array('component').transpose(...,'component')
            selected = xr.Dataset(sample).to_array('component')
            dist = (selected - available).pipe(np.square).sum('component') #no sqrt needed for just min distance
            sample_index = dist.argmin()
            
            # Get the data variables from grid_data and add them individually to sample dict
            grid_sample = self.grid_data.isel(sample=sample_index).reset_coords()
            for var_name in grid_sample.data_vars:
                sample[var_name] = grid_sample[var_name].item()
            self.update_status(f"Found closest sample to be {grid_sample}")

            # Generate sample name if not provided
            if name is None:
                self.sample_name = f"{self.config['data_tag']}_{self.uuid['sample'][-8:]}"
            else:
                self.sample_name = name
        
            # Measure the sample
            self.measure_grid_sample(sample, name=self.sample_name, empty=False)
            self.construct_grid_datasets(sample)
        
            # update sample manifest and grid data
            self.num_samples = self.grid_data.sizes['sample']#update num samples
            self.grid_data = self.grid_data.drop_isel(sample=sample_index)
            self.grid_sample_count += 1
        
        # Predict next sample if requested
        if predict_next:
            if sample is not None:
                self.add_new_data_to_agent()
            self.predict_next_sample()
            
        # Enqueue next sample if requested
        if enqueue_next:
            ag_result = self.get_client('agent').retrieve_obj(uid=self.uuid['agent'])
            next_samples = ag_result[self.config['next_samples_variable']]
            
            new_composition = next_samples.to_pandas().squeeze().to_dict()
            new_composition = {k:v for k,v in new_composition.items()}

            task = {
                'task_name': 'process_sample_grid',
                'sample': new_composition,
                'predict_next': predict_next,
                'enqueue_next': enqueue_next,
                'AL_campaign_name': self.AL_campaign_name,
                'AL_uuid': self.uuid['AL'],
            }
            
            task_uuid = 'QD-' + str(uuid.uuid4())
            package = {'task': task, 'meta': {}, 'uuid': task_uuid}
            package['meta']['queued'] = datetime.datetime.now().strftime('%m/%d/%y %H:%M:%S-%f')
            
            queue_loc = self._queue.qsize()  # append at end of queue
            self._queue.put(package, queue_loc)
    
    def measure_grid_sample(self, sample, name, empty=False):
        """Measure a sample using the grid-based workflow.

        instrument = {
            'client_name': 'APSUSAXS',
            'empty_base_kw': {'task_name': 'expose'},
            'measure_base_kw': {'task_name': 'expose'},
            'select_sample_base_kw': {'task_name': 'setPosition', 'y_offset': 2},
            'sample_select_kwargs': ['plate', 'row', 'col'],
            'sample_comps_variable': 'sample_composition'
        }
        
        Parameters
        ----------
        sample: Dict
            Dictionary containing sample coordinates and properties
            
        name: str
            Sample name for the measurement
        


        """
        self.update_status(f"Starting measurement of {name}")
        
        # Set sample information in all clients
        sample_data = self.set_sample(
            sample_name=name,
            sample_uuid=self.uuid['sample'],
            AL_campaign_name=self.AL_campaign_name,
            AL_uuid=self.uuid['AL'],
            AL_components=self.config['AL_components'],
            sample_composition=sample,
        )
        
        for client_name in self.config['client'].keys():
            self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)

        
        # Move to the sample position based on instrument configuration
        for i, instrument in enumerate(self.config['instrument']):
            self.update_status(f"Moving to sample position using global command template")
            move_cmd_kwargs = {k:sample[k] for k in instrument['sample_select_kwargs']}
            move_cmd_kwargs.update(instrument['select_sample_base_kw'])
            self.uuid['move'] = self.get_client(instrument['client_name']).enqueue(**move_cmd_kwargs)
            self.get_client(instrument['client_name']).wait(self.uuid['move'])


            self.update_status(f"Measuring sample with {instrument['client_name']}")
            measure_cmd_kwargs = instrument['measure_base_kw'] if not empty else instrument['empty_base_kw']
            measure_cmd_kwargs['name'] = name
            self.uuid['measure'] = self.get_client(instrument['client_name']).enqueue(**measure_cmd_kwargs)
            self.get_client(instrument['client_name']).wait(self.uuid['measure'])

        
        self.update_status(f'All done for {name}!')
    
    def construct_grid_datasets(self, sample: dict):
        """Construct datasets from grid-based measurements"""
        data_path = pathlib.Path(self.config['data_path'])

        if self.tiled_client is None:
            self.tiled_client = self.data.tiled_client
            # this needs to be here, because in the constructor, we don't have the datapacket attached

        self.new_data = xr.Dataset()
        for i, instrument in enumerate(self.config['instrument']):
            for k in instrument['sample_select_kwargs']:
                self.new_data[k] = sample[k]
                self.new_data[k].attrs['description'] = 'sample coordinate'

            for instrument_data in instrument['data']:
                tiled_result = (
                    self.tiled_client
                    .search(Eq('sample_uuid', self.uuid['sample']))
                    .search(Eq('array_name', instrument_data['tiled_array_name']))
                )
                if len(tiled_result) == 0:
                    raise ValueError(f"Could not find tiled entry for measurement sample_uuid={self.uuid['sample']}")

                # handle Python None and "None" depending on how json deserialization works out
                if (instrument_data['data_dim'] is not None) and (instrument_data['data_dim'] != 'None'):
                    # first try to read this as an array entry in tiled, if not found, look in metadata
                    tiled_result_dim = (
                        self.tiled_client
                        .search(Eq('sample_uuid', self.uuid['sample']))
                        .search(Eq('array_name', instrument_data['data_dim']))
                    )
                    if len(tiled_result_dim)>0:
                        dims = instrument_data['data_dim']
                        coords = {instrument_data['data_dim']: tiled_result_dim.values()[-1].read()}
                    else:
                        dims = instrument_data['data_dim']
                        coords = {instrument_data['data_dim']: tiled_result.items()[-1][-1].metadata[
                            instrument_data['tiled_metadata_dim']]}
                else:
                    dims = None
                    coords = None

                if 'sample_env' in instrument.keys():

                    sample_env_dims = list(instrument['sample_env']['move_swept_kw'].keys())

                    measurement_list = []
                    for _,tiled_data in tiled_result.items():
                        if 'MT-' in tiled_data.metadata['name']:
                            continue
                        measurement_list.append(xr.DataArray(tiled_data[()], dims=dims, coords=coords))
                    measurement = xr.concat(measurement_list, dim=instrument['sample_dim'])
                    for key,values in instrument['sample_env']['move_swept_kw'].items():
                        measurement[key] = (instrument['sample_dim'],values)
                    self.new_data[instrument_data['data_name']] = measurement
                else:

                    tiled_data = tiled_result.items()[-1][-1]
                    measurement = xr.DataArray(tiled_data[()], dims=dims, coords=coords)
                    self.new_data[instrument_data['data_name']] = measurement

                if 'quality_metric' in instrument.keys():
                    quality_metric = instrument['quality_metric']
                    instrument_value = tiled_data.metadata[quality_metric['tiled_metadata_key']]
                    if quality_metric['comparison'].lower() in ['<', 'lt']:
                        accept = instrument_value < quality_metric['threshold']
                    elif quality_metric['comparison'].lower() in ['>', 'gt']:
                        accept = instrument_value > quality_metric['threshold']
                    elif quality_metric['comparison'].lower() in ['==', '=', 'eq']:
                        accept = instrument_value == quality_metric['threshold']
                    else:
                        raise ValueError(
                            f'Cannot recognize comparison for quality_metric. You passed {quality_metric["comparison"]}')
                else:
                    accept = True
                self.new_data[instrument_data['data_name']].attrs['accept'] = int(accept)

        self.new_data['sample_uuid'] = self.uuid['sample']

        sample_composition = {}
        for component in self.config['components']:
            try:
                self.new_data[component] = sample[component]

                # for tiled
                sample_composition[component] = sample[component]
            except KeyError:
                warnings.warn(f"Skipping component {component} in AL_components")


        self.new_data.to_netcdf(data_path / (self.sample_name + '.nc'))

        sample_composition['components'] = self.config['components']
        if self.data is not None:
            self.data['sample_composition'] = sample_composition
            self.data['time'] = datetime.datetime.now().strftime('%m/%d/%y %H:%M:%S-%f %Z%z')
        
    

    def set_sample(self, 
                  sample_name: str, 
                  sample_uuid: str, 
                  AL_campaign_name: Optional[str] = None,
                  AL_uuid: Optional[str] = None,
                  AL_components: Optional[List] = None,
                  sample_composition: Optional[Dict] = None):
        """Set sample information for all clients
        
        Parameters
        ----------
        sample_name: str
            Name of the sample
            
        sample_uuid: str
            UUID of the sample
            
        AL_campaign_name: str, optional
            Name of the AL campaign
            
        AL_uuid: str, optional
            UUID of the AL campaign
            
        AL_components: List, optional
            List of components for AL
            
        sample_composition: Dict, optional
            Composition of the sample
            
        Returns
        -------
        Dict
            Sample data for client communication
        """
        sample_data = {
            'sample_name': sample_name,
            'sample_uuid': sample_uuid,
        }
        
        if AL_campaign_name is not None:
            sample_data['AL_campaign_name'] = AL_campaign_name
            
        if AL_uuid is not None:
            sample_data['AL_uuid'] = AL_uuid
            
        if AL_components is not None:
            sample_data['AL_components'] = AL_components
            
        if sample_composition is not None:
            sample_data['sample_composition'] = sample_composition
            
        return sample_data

    # New grid reset methods
    @Driver.quickbar(qb={'button_text':'Reset Grid'})
    def reset_grid(self):
        """Reload the grid from file and reset grid_sample_count."""
        if self.config['grid_file'] is None:
            self.app.logger.info("No grid file specified in configuration.")
            self.grid_data = None
            self.grid_sample_count = 0
        else:
            self.grid_data = xr.load_dataset(self.config['grid_file'])
            self.grid_sample_count = 0
            self.app.logger.info(f"Grid reloaded: {self.grid_data.sizes['sample']} samples available.")
    

_DEFAULT_CUSTOM_CONFIG = {

    '_classname': 'AFL.automation.sample.SampleDriver.SampleDriver',
}

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
