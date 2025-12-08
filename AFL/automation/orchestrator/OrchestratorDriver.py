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

from AFL.automation.APIServer.Client import Client  # type: ignore
from AFL.automation.APIServer.Driver import Driver  # type: ignore
from AFL.automation.mixing.Solution import Solution  # type: ignore
from AFL.automation.shared.units import units  # type: ignore


class OrchestratorDriver(Driver):
    """

    PersistentConfig Values
    -----------------------
    client: dict
        Contains APIServer uris (url:port) where the keys will be used as the accessor names.

    instrument: list[dict]
        List of instrument configurations. Each instrument dict should contain:

        Required fields:
        - name (str): Instrument identifier
        - client_name (str): Key from client dict for this instrument
        - measure_base_kw (dict): Base kwargs for measurement task
        - empty_base_kw (dict): Base kwargs for empty/background measurement task
        - concat_dim (str): Dimension name for AgentDriver tiled_input_groups

        Optional fields:
        - variable_prefix (str): Prefix for AgentDriver tiled_input_groups (default: '')
        - load_dest_label (str): Destination label for sample loading
        - quality_metric (dict): Quality validation criteria
        - sample_env (dict): Sample environment sweep configuration

    ternary: bool
        If true, process coordinates as ternary, Barycentric values

    data_tag: str
        Label for current measurements or active learning run

    composition_format: str or dict
        Format for extracting composition from balanced_target after preparation.

        If str: Single format applied to all components
            Valid values: 'mass_fraction', 'volume_fraction', 'concentration', 'molarity'

        If dict: Per-component format specification
            Example: {"H2O": "mass_fraction", "NaCl": "concentration"}
            Keys are component names, values are format strings (same valid values as above)

        Default: 'mass_fraction'
    """

    defaults = {}
    defaults['client'] = {}
    defaults['instrument'] = {}
    defaults['ternary'] = False
    defaults['data_tag'] = 'default'
    defaults['data_path'] = './'
    defaults['components'] = []
    defaults['AL_components'] = []
    defaults['snapshot_directory'] = '/home/nistoroboto'
    defaults['max_sample_transmission'] = 0.6
    defaults['mix_order'] = []
    defaults['camera_urls'] = []
    defaults['snapshot_directory'] = []
    defaults['grid_file'] = None
    defaults['grid_blank_interval'] = None
    defaults['grid_blank_sample'] = None
    defaults['prepare_volume'] = '1000 ul'
    defaults['empty_prefix'] = 'MT-'
    defaults['composition_format'] = 'mass_fraction'
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

        Driver.__init__(self, name='OrchestratorDriver', defaults=self.gather_defaults(), overrides=overrides)

        self.AL_campaign_name = None
        self.sample_name: Optional[str] = None
        self.app = None
        self.name = 'OrchestratorDriver'

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
        self.balanced_target = None

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
            # New simplified instrument schema (AgentDriver reads from tiled directly)
            required_instrument_keys = ['name', 'client_name', 'measure_base_kw', 'empty_base_kw', 'concat_dim']
            missing_instrument_keys = [key for key in required_instrument_keys if key not in instrument]
            if missing_instrument_keys:
                raise KeyError(f"Instrument {i} is missing the following required keys: {', '.join(missing_instrument_keys)}")

            # Optional keys: variable_prefix, load_dest_label, quality_metric, sample_env
            # No validation needed for optional keys

        # Validate other list types
        list_keys = ['components', 'AL_components', 'camera_urls']
        for key in list_keys:
            if not isinstance(self.config[key], list):
                raise TypeError(f"self.config['{key}'] must be a list")

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

        # Validate composition_format if present
        if 'composition_format' in self.config:
            comp_fmt = self.config['composition_format']
            valid_formats = ['mass_fraction', 'volume_fraction', 'concentration', 'molarity']

            if isinstance(comp_fmt, str):
                # Single format for all components
                if comp_fmt not in valid_formats:
                    raise ValueError(
                        f"Invalid composition_format '{comp_fmt}'. "
                        f"Must be one of: {', '.join(valid_formats)}"
                    )
            elif isinstance(comp_fmt, dict):
                # Per-component format specification
                for component, format_type in comp_fmt.items():
                    if format_type not in valid_formats:
                        raise ValueError(
                            f"Invalid format '{format_type}' for component '{component}'. "
                            f"Must be one of: {', '.join(valid_formats)}"
                        )
            else:
                raise TypeError(
                    f"composition_format must be str or dict, got {type(comp_fmt).__name__}"
                )

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
            client.login("Orchestrator")
            client.debug(False)

        return client

    def take_snapshot(self, prefix):
        now = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
        for i, cam_url in enumerate(self.config['camera_urls']):
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


    def process_sample(
            self,
            sample: Dict,
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

        sample: Dict
            Solution-compatible dictionary containing sample definition. Should include:
            - 'name': str (optional, can be overridden by name parameter)
            - 'concentrations' or 'mass_fractions': Dict with component specifications
            - 'total_volume': str or pint.Quantity (optional, uses config default if not provided)
            - Other Solution constructor kwargs (masses, volumes, location, solutes, etc.)
            If 'total_volume' is not provided, will use self.config['prepare_volume'].

        predict_combine_comps: Optional[Dict]
            Dictionary for combining components in dataset construction

        predict_next: bool
            If True, will trigger predict call to the agent

        enqueue_next: bool
            If True, will pull the next sample from the dropbox of the agent

        calibrate_sensor: bool
            If True, trigger a load stopper sensor recalibration before the next measurement

        name: str, optional
            The name of the sample. If not provided, will use sample['name'] if present,
            otherwise auto-generated from self.config['data_tag'] and uuid

        sample_uuid: str, optional
            uuid of sample, if not specified it will be auto-generated

        AL_uuid: str, optional
            uuid of AL campaign

        AL_campaign_name: str, optional
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

        # Extract name from sample dict if not provided as parameter
        if name is None:
            if 'name' in sample:
                self.sample_name = sample['name']
            else:
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
       
        # Ensure sample has total_volume set
        sample_target = sample.copy()
        if 'total_volume' not in sample_target:
            sample_target['total_volume'] = self.config['prepare_volume']
        
        # Ensure sample has name set
        if 'name' not in sample_target:
            sample_target['name'] = self.sample_name

        print(f'Sample: {sample_target}')
        if sample_target: # sample is not empty
            # Check if the requested composition is feasible
            feasibility_result = self.get_client('prep').enqueue(
                task_name='is_feasible',
                targets=[sample_target],
                interactive=True
            )['return_val']
            
            if feasibility_result[0] is None:
                self.update_status("Requested composition is not feasible with available stocks.")
                return False # update this
            
            # Pass the sample dict to make_and_measure which will handle preparation, balance_report, and set_sample
            self.make_and_measure(
                name=self.sample_name,
                sample=sample_target,
                calibrate_sensor=calibrate_sensor
            )

        if enqueue_next or predict_next:
            self.predict_next_sample()

        # Look away ... here be dragons ...
        if enqueue_next:
            ag_result = self.get_client('agent').retrieve_obj(uid=self.uuid['agent'])
            next_samples = ag_result['next_samples']
            
            # Convert next_samples to Solution-compatible format
            new_sample = next_samples.to_pandas().squeeze().to_dict()
            # Convert to concentrations format for Solution
            new_sample_dict = {
                'concentrations': {k: f"{v} mg/ml" for k, v in new_sample.items()},
                'name': f"sample_{self.uuid['sample'][-8:]}"
            }

            task = {
                'task_name':'process_sample',
                'sample': new_sample_dict,
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

    def make_and_measure(
            self,
            name: str,
            sample: Dict,
            calibrate_sensor: bool = False,
    ):
        self.update_status(f'starting make and measure for {name}')

        # NEW WORKFLOW: Set sample on prep first (without composition), then prepare, then get composition
        # Step 1: Call set_sample on prep robot with ONLY sample_uuid and AL_* parameters
        prep_sample_data = {
            'sample_name': name,
            'sample_uuid': self.uuid['sample'],
        }
        if self.uuid.get('AL'):
            prep_sample_data['AL_uuid'] = self.uuid['AL']
        if self.AL_campaign_name:
            prep_sample_data['AL_campaign_name'] = self.AL_campaign_name
        if self.config.get('AL_components'):
            prep_sample_data['AL_components'] = self.config['AL_components']

        self.get_client('prep').enqueue(task_name='set_sample', **prep_sample_data)

        # Step 2: Start preparation (async)
        self.update_status(f'Preparing sample {name}...')
        self.uuid['prep'] = self.get_client('prep').enqueue(
            task_name='prepare',
            target=sample,
            dest=None,  # Let the prepare server assign a location
            interactive=False
        )

        if self.uuid['rinse'] is not None:
            self.update_status(f'Waiting for rinse...')
            self.get_client('load').wait(self.uuid['rinse'], for_history=False)
            self.update_status(f'Rinse done!')

        if calibrate_sensor:
            # calibrate sensor to avoid drift
            self.get_client('load').enqueue(task_name='calibrate_sensor')

        # Measure empty cell first
        self.update_status(f'Cell is clean, measuring empty cell scattering...')
        self.measure(name=name, empty=True, wait=True)

        # Step 3: Wait for preparation to finish
        if self.uuid['prep'] is not None:
            self.update_status(f"Waiting for sample prep of {name} to finish: {self.uuid['prep'][-8:]}")
            prep_task_result = self.get_client('prep').wait(self.uuid['prep'])

            if prep_task_result.get('status') == 'failed':
                error_msg = f"Sample preparation failed for {name}: {prep_task_result.get('error')}"
                self.update_status(error_msg)
                self.app.logger.error(error_msg)
                return False

            self.take_snapshot(prefix=f'02-after-prep-{name}')

            # Step 4: Call balance_report interactively to get actual composition
            self.update_status(f'Getting balanced composition from prep robot...')
            balance_result = self.get_client('prep').enqueue(
                task_name='balance_report',
                interactive=True
            )

            if not balance_result or balance_result.get('status') == 'failed':
                error_msg = f"Failed to get balance_report for {name}"
                self.update_status(error_msg)
                self.app.logger.error(error_msg)
                return False

            balance_report = balance_result.get('return_val')
            if not balance_report or len(balance_report) == 0:
                error_msg = f"balance_report returned empty for {name}"
                self.update_status(error_msg)
                self.app.logger.error(error_msg)
                return False

            # Extract the last balanced_target from report (most recent)
            last_entry = balance_report[-1]
            balanced_target_dict = last_entry.get('balanced_target')

            if not balanced_target_dict:
                error_msg = f"No balanced_target in balance_report for {name}"
                self.update_status(error_msg)
                self.app.logger.error(error_msg)
                return False

            # Step 5: Transform masses to configured composition format
            masses = balanced_target_dict.get('masses', {})
            sample_composition = self._transform_composition(masses)

            # Step 6: Store compositions in data for reference
            self.data['sample_composition_target'] = sample
            self.data['sample_composition_realized'] = sample_composition

            # Step 7: Call set_sample on Orchestrator and all clients with realized composition
            sample_data = self.set_sample(
                sample_name=name,
                sample_uuid=self.uuid['sample'],
                AL_campaign_name=self.AL_campaign_name,
                AL_uuid=self.uuid['AL'],
                AL_components=self.config.get('AL_components'),
                sample_composition=sample_composition,
            )

            for client_name in self.config['client'].keys():
                self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)

            # Get solution location from prepare result for transfer_to_catch
            prepare_result = prep_task_result.get('return_val')
            if prepare_result and len(prepare_result) > 1:
                solution_location = prepare_result[1]
            else:
                solution_location = balanced_target_dict.get('location')
            
            self.update_status(f'Queueing sample {name} load into syringe loader')
            # Use transfer_to_catch method which handles catch protocol and destination internally
            self.uuid['catch'] = self.get_client('prep').enqueue(
                task_name='transfer_to_catch',
                source=solution_location,
            )

            if self.uuid['catch'] is not None:
                self.update_status(f"Waiting for sample prep/catch of {name} to finish: {self.uuid['catch'][-8:]}")
                catch_result = self.get_client('prep').wait(self.uuid['catch'])
                
                # Check for failure in the catch task
                if catch_result and isinstance(catch_result, dict) and catch_result.get('status') == 'failed':
                    error_msg = f"Transfer to catch failed for {name}: {catch_result.get('error')}"
                    self.update_status(error_msg)
                    self.app.logger.error(error_msg)
                    # Assuming interactive pause/wait is needed here? Or just return False?
                    # For now, return False to stop the process for this sample
                    return False
                    
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
            name = self.config['empty_prefix'] + name

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
                if not measure_kw: # if empty_base_kw is empty, skip the empty on this instrument
                    continue
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

                # Collect entry_ids from all sample_env measurements
                entry_ids = []

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

                    # Query tiled for entry_id from this measurement
                    task_name = measure_kw.get('task_name')
                    entry_id = self._get_last_tiled_entry_for_measurement(
                        sample_uuid=self.uuid['sample'],
                        task_name=task_name
                    )
                    if entry_id:
                        entry_ids.append(entry_id)

                # After all sample_env measurements, append all entry_ids to AgentDriver
                if entry_ids and 'agent' in self.config['client']:
                    self._append_to_agent_input_groups(instrument, entry_ids)

                # # move sample environment to initial starting state to prepare for next measurement
                # sample_env_kw = {}
                # sample_env_kw.update(starting_condition)
                # sample_env_kw.update(instrument['sample_env']['move_base_kw'])
                # self.uuid['move_sample_env'] = self.get_client(instrument['sample_env']['client_name']).enqueue(**sample_env_kw)

            else:
                self.uuid['measure'] = self.get_client(instrument['client_name']).enqueue(**measure_kw)

                if wait:
                    self.get_client(instrument['client_name']).wait(self.uuid['measure'])

                    # Query tiled for entry_id from this measurement
                    if not empty and 'agent' in self.config['client']:
                        task_name = measure_kw.get('task_name')
                        entry_id = self._get_last_tiled_entry_for_measurement(
                            sample_uuid=self.uuid['sample'],
                            task_name=task_name
                        )
                        if entry_id:
                            self._append_to_agent_input_groups(instrument, [entry_id])

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

            # update sample manifest and grid data
            self.num_samples = self.grid_data.sizes['sample']#update num samples
            self.grid_data = self.grid_data.drop_isel(sample=sample_index)
            self.grid_sample_count += 1
        
        # Predict next sample if requested
        if predict_next:
            self.predict_next_sample()

        # Enqueue next sample if requested
        if enqueue_next:
            ag_result = self.get_client('agent').retrieve_obj(uid=self.uuid['agent'])
            next_samples = ag_result['next_samples']
            
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

    def _transform_composition(self, masses_dict: Dict[str, str]) -> Dict:
        """Transform mass dictionary to configured composition format.

        Parameters
        ----------
        masses_dict : Dict[str, str]
            Dictionary with component names as keys and mass strings as values
            Example: {"H2O": "950 mg", "NaCl": "50 mg"}

        Returns
        -------
        Dict
            Composition dictionary with components in requested format

        Raises
        ------
        ValueError
            If composition_format is invalid or required data is missing
        """
        from AFL.automation.mixing.Solution import Solution

        # Get composition_format from config (default to mass_fraction for all)
        composition_format = self.config.get('composition_format', 'mass_fraction')

        # Create a temporary Solution object from the masses
        # This allows us to access all conversion methods
        temp_solution = Solution(
            name='temp',
            masses=masses_dict,
            sanity_check=False
        )

        sample_composition = {}

        # Determine format for each component
        if isinstance(composition_format, str):
            # Single format for all components
            for component in temp_solution.components.keys():
                sample_composition[component] = self._get_component_value(
                    temp_solution, component, composition_format
                )
        elif isinstance(composition_format, dict):
            # Different format per component - include ALL components
            for component in temp_solution.components.keys():
                format_type = composition_format.get(component, 'mass_fraction')
                sample_composition[component] = self._get_component_value(
                    temp_solution, component, format_type
                )
        else:
            raise ValueError(
                f"composition_format must be str or dict, got {type(composition_format)}"
            )

        return sample_composition

    def _get_component_value(self, solution: 'Solution', component: str, format_type: str) -> float:
        """Extract component value in specified format from Solution object.

        Parameters
        ----------
        solution : Solution
            Solution object containing the component
        component : str
            Component name
        format_type : str
            One of: 'mass_fraction', 'volume_fraction', 'concentration', 'molarity'

        Returns
        -------
        float
            Component value in requested format (dimensionless)

        Raises
        ------
        ValueError
            If format_type is invalid or component doesn't support the format
        """
        if format_type == 'mass_fraction':
            return solution.mass_fraction[component].magnitude

        elif format_type == 'volume_fraction':
            # Only solvents have volume_fraction
            if solution[component].volume is None:
                raise ValueError(
                    f"Component {component} has no volume, cannot calculate volume_fraction. "
                    f"Only solvents support volume_fraction."
                )
            return solution.volume_fraction[component].magnitude

        elif format_type == 'concentration':
            # Returns mg/ml
            return solution.concentration[component].to('mg/ml').magnitude

        elif format_type == 'molarity':
            # Returns mM (requires formula)
            if not hasattr(solution[component], 'formula') or solution[component].formula is None:
                raise ValueError(
                    f"Component {component} has no formula, cannot calculate molarity"
                )
            return solution.molarity[component].to('mM').magnitude

        else:
            raise ValueError(
                f"Invalid format_type '{format_type}'. "
                f"Must be one of: 'mass_fraction', 'volume_fraction', 'concentration', 'molarity'"
            )

    def _get_last_tiled_entry_for_measurement(self, sample_uuid: str, task_name: str) -> Optional[str]:
        """Query tiled for the last entry matching sample_uuid and task_name.

        Parameters
        ----------
        sample_uuid : str
            Sample UUID to search for
        task_name : str
            Task name to filter by

        Returns
        -------
        str or None
            Entry ID if found, None otherwise
        """
        try:
            # Get tiled client from config
            if 'tiled_uri' not in self.config or not self.config['tiled_uri']:
                self.app.logger.warning("No tiled_uri configured, cannot query for entry_id")
                return None

            from tiled.client import from_uri

            # Connect to tiled
            client = from_uri(self.config['tiled_uri'])

            # Search for entries with matching sample_uuid in metadata
            matching_entries = []
            for entry_id in client:
                entry = client[entry_id]
                metadata = getattr(entry, 'metadata', {})

                # Check if sample_uuid matches
                if metadata.get('sample_uuid') == sample_uuid:
                    # Check if task_name matches (if provided)
                    if task_name is None or metadata.get('task_name') == task_name:
                        # Get timestamp or use entry order
                        timestamp = metadata.get('timestamp', 0)
                        matching_entries.append((entry_id, timestamp))

            if not matching_entries:
                self.app.logger.warning(f"No tiled entry found for sample_uuid={sample_uuid}, task_name={task_name}")
                return None

            # Sort by timestamp and return the last one
            matching_entries.sort(key=lambda x: x[1], reverse=True)
            return matching_entries[0][0]

        except Exception as e:
            self.app.logger.error(f"Error querying tiled for entry_id: {e}")
            return None

    def _append_to_agent_input_groups(self, instrument: Dict, entry_ids: List[str]) -> None:
        """Append measurement entry_ids to AgentDriver's tiled_input_groups config.

        Parameters
        ----------
        instrument : Dict
            Instrument config containing concat_dim and variable_prefix
        entry_ids : List[str]
            Entry IDs from tiled to append to the group
        """
        # Step 1: Get current config from AgentDriver (direct return, no return_val)
        current_groups = self.get_client('agent').get_config('tiled_input_groups')

        if current_groups is None:
            current_groups = []

        # Step 2: Find matching group by concat_dim and variable_prefix
        concat_dim = instrument.get('concat_dim')
        variable_prefix = instrument.get('variable_prefix', '')

        group_found = False
        for group in current_groups:
            if group.get('concat_dim') == concat_dim and group.get('variable_prefix') == variable_prefix:
                # Append new entry_ids to existing group
                group['entry_ids'].extend(entry_ids)
                group_found = True
                break

        # Step 3: If no matching group exists, create new one
        if not group_found:
            current_groups.append({
                'concat_dim': concat_dim,
                'variable_prefix': variable_prefix,
                'entry_ids': entry_ids
            })

        # Step 4: Update AgentDriver config (direct, no interactive)
        self.get_client('agent').set_config('tiled_input_groups', current_groups)

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

    '_classname': 'AFL.automation.orchestrator.OrchestratorDriver.OrchestratorDriver',
    'snapshot_directory': '/home/afl642/snaps'
}

_DEFAULT_PORT=5000

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
