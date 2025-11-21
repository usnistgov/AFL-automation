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
    defaults['snapshot_directory'] = '/home/nistoroboto'
    defaults['max_sample_transmission'] = 0.6
    defaults['mix_order'] = []
    defaults['composition_var_name'] = 'comps'
    defaults['concat_dim'] = 'sample'
    defaults['sample_composition_tol'] = 0.0
    defaults['next_samples_variable'] = 'next_samples'
    defaults['camera_urls'] = []
    defaults['tiled_exclusion_list'] = []
    defaults['snapshot_directory'] = []
    defaults['grid_file'] = None
    defaults['grid_blank_interval'] = None
    defaults['grid_blank_sample'] = None
    defaults['prepare_volume'] = '1000 ul'

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
        list_keys = ['components', 'AL_components', 'camera_urls', 'tiled_exclusion_list']
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
            
            # Extract the realized composition from feasibility result
            sample_composition_realized = feasibility_result[0]
            
            # Update sample information with target and realized compositions
            self.data['sample_composition_target'] = sample_target
            self.data['sample_composition_realized'] = sample_composition_realized
            
            # Set sample info for all servers with realized composition
            sample_data = self.set_sample(
                sample_name=self.sample_name,
                sample_uuid=self.uuid['sample'],
                AL_campaign_name=self.AL_campaign_name,
                AL_uuid=self.uuid['AL'],
                AL_components=self.config['AL_components'],
                sample_composition=sample_composition_realized,
            )
            
            for client_name in self.config['client'].keys():
                if client_name not in self.config['tiled_exclusion_list']:
                    self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)
            
            # Pass the sample dict to make_and_measure which will handle the actual preparation and measurements
            self.make_and_measure(
                name=self.sample_name, 
                sample=sample_target,
                calibrate_sensor=calibrate_sensor
            )
            self.construct_datasets(combine_comps=predict_combine_comps)

        if enqueue_next or predict_next:
            if sample_target:#assume we made/measured a sample and append
                self.add_new_data_to_agent()
            self.predict_next_sample()

        # Look away ... here be dragons ...
        if enqueue_next:
            ag_result = self.get_client('agent').retrieve_obj(uid=self.uuid['agent'])
            next_samples = ag_result[self.config['next_samples_variable']]
            
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
        
        # Now prepare the sample - we already know it's feasible from earlier check
        self.update_status(f'Preparing sample {name}...')
        prepare_result = self.get_client('prep').enqueue(
            task_name='prepare',
            target=sample,
            dest=None,  # Let the prepare server assign a location
            interactive=True
        )['return_val']
        
        if all(p is None for p in prepare_result):
            self.update_status(f'Failed to prepare sample {name}')
            return False
            
        # Extract result: (balanced_target_dict, solution_location)
        balanced_target_dict = prepare_result[0]
        solution_location = prepare_result[1]
        
        # Reconstruct balanced_target Solution object from dict for use in construct_datasets
        # The dict contains: name, components (list), masses (dict with "value mg" strings), total_volume (optional)
        # Create Solution with masses dict directly
        solution_kwargs = {
            'name': balanced_target_dict.get('name', name),
            'masses': balanced_target_dict.get('masses', {}),
        }
        
        # Add total_volume if provided
        if 'total_volume' in balanced_target_dict:
            total_vol_str = balanced_target_dict['total_volume']
            if isinstance(total_vol_str, str):
                solution_kwargs['total_volume'] = total_vol_str
            elif isinstance(total_vol_str, dict) and 'value' in total_vol_str and 'units' in total_vol_str:
                solution_kwargs['total_volume'] = f"{total_vol_str['value']} {total_vol_str['units']}"
            else:
                solution_kwargs['total_volume'] = total_vol_str
        
        # Disable sanity check since we're reconstructing from a balanced solution
        solution_kwargs['sanity_check'] = False
        self.balanced_target = Solution(**solution_kwargs)
        
        # Extract sample_volume from sample dict or use a default
        # Check if sample_volume is specified in the sample dict
        sample_volume = None
        if 'sample_volume' in sample:
            sample_volume = sample['sample_volume']
        elif 'transfer_volume' in sample:
            sample_volume = sample['transfer_volume']
        else:
            # Use a default based on catch_volume config or prepare_volume
            default_volume = self.config.get('catch_volume', '10 ul')
            if isinstance(default_volume, str):
                sample_volume = {'value': units(default_volume).magnitude, 'units': str(units(default_volume).units)}
            else:
                sample_volume = default_volume
        
        # Convert sample_volume to dict format if needed
        if isinstance(sample_volume, str):
            vol_quantity = units(sample_volume)
            sample_volume = {'value': vol_quantity.magnitude, 'units': str(vol_quantity.units)}
        elif isinstance(sample_volume, dict) and 'value' in sample_volume and 'units' in sample_volume:
            pass  # Already in correct format
        else:
            # Try to parse as quantity
            vol_quantity = units(sample_volume)
            sample_volume = {'value': vol_quantity.magnitude, 'units': str(vol_quantity.units)}
        
        # Safety check: Verify prepared volume is sufficient for sample_volume
        if hasattr(self.balanced_target, 'volume') and self.balanced_target.volume is not None:
            prepared_volume = self.balanced_target.volume
            sample_volume_quantity = units(f"{sample_volume['value']} {sample_volume['units']}")
            
            if prepared_volume < sample_volume_quantity:
                error_msg = (
                    f"Prepared volume ({prepared_volume}) is less than required sample volume "
                    f"({sample_volume_quantity}) for sample {name}"
                )
                self.update_status(error_msg)
                raise ValueError(error_msg)
        else:
            self.app.logger.warning(
                f"No total_volume in prepare result for {name}, skipping volume safety check"
            )
        
        # Transfer sample from preparation unit to catch/loader
        self.update_status(f'Transferring sample {name} to catch/loader')
        
        # Convert sample_volume to volume string for transfer
        volume_str = f"{sample_volume['value']} {sample_volume['units']}"
        
        # Use transfer_to_catch method which handles catch protocol and destination internally
        self.uuid['catch'] = self.get_client('prep').enqueue(
            task_name='transfer_to_catch',
            source=solution_location,
            volume=volume_str
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

        self.new_data['sample_uuid'] = self.uuid['sample']

        # Use balanced_target Solution object from make_and_measure
        if not hasattr(self, 'balanced_target') or self.balanced_target is None:
            raise ValueError("balanced_target not available. make_and_measure must be called before construct_datasets.")
        
        balanced_target = self.balanced_target
        
        sample_composition = {}
        if self.config['ternary']:
            total = 0
            for component in self.config['AL_components']:
                mf = balanced_target.mass_fraction[component].magnitude
                self.new_data[component] = mf
                total += mf
            for component in self.config['AL_components']:
                self.new_data[component] = self.new_data[component] / total

                # for tiled
                sample_composition['ternary_mfrac_' + component] = balanced_target.concentration[
                    component].to("mg/ml").magnitude
        else:
            for component in self.config['AL_components']:
                try:
                    self.new_data[component] = balanced_target.concentration[component].to("mg/ml").magnitude
                    self.new_data[component].attrs['units'] = 'mg/ml'

                    # for tiled
                    sample_composition['conc_' + component] = balanced_target.concentration[component].to(
                    "mg/ml").magnitude
                except KeyError:
                    warnings.warn(f"Skipping component {component} in AL_components")

        for component in self.config['components']:
            self.new_data['mfrac_' + component] = balanced_target.mass_fraction[component].magnitude
            self.new_data['mass_' + component] = balanced_target[component].mass.to('mg').magnitude
            self.new_data['mass_' + component].attrs['units'] = 'mg'
            if balanced_target[component].volume is not None:
                self.new_data['volume_' + component] = balanced_target[component].volume.to('ml').magnitude
                self.new_data['volume_' + component].attrs['units'] = 'ml'

            # for tiled
            sample_composition['mfrac_' + component] = balanced_target.mass_fraction[component].magnitude
            sample_composition['mass_' + component] = balanced_target[component].mass.to('mg').magnitude

        if combine_comps is not None:
            for new_component,combine_list in combine_comps.items():
                conc = 0 * units('mg/ml')
                mass = 0 * units('mg')
                volume = 0 * units('ul')
                for component in combine_list:
                    conc += balanced_target.concentration[component].to("mg/ml")
                    mass += balanced_target[component].mass.to("mg")
                    volume += balanced_target[component].volume.to("ul")

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

    '_classname': 'AFL.automation.orchestrator.OrchestratorDriver.OrchestratorDriver',
    'snapshot_directory': '/home/afl642/snaps'
}

_DEFAULT_PORT=5000

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
