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
from AFL.automation.orchestrator.OrchestratorDriver import OrchestratorDriver  # type: ignore


class OrchestratorGridDriver(OrchestratorDriver):
    """
    Subclass of OrchestratorDriver that supports pre-prepared sample grids.
    
    Instead of preparing arbitrary samples, finds the closest sample in a pre-prepared
    grid and executes custom actions to load/position that grid sample.

    PersistentConfig Values
    -----------------------
    All values from OrchestratorDriver, plus:
    
    grid_file: str or None
        Path to NetCDF file with xarray Dataset containing grid samples
        
    grid_entry_id: str or None
        Tiled entry_id for grid (alternative to grid_file, preferred for persistence/sharing)
        
    grid_blank_interval: int or None
        Measure blank every N samples (e.g., every 10 samples)
        
    grid_blank_sample: dict or None
        Dictionary defining blank sample kwargs for measurement
        
    Instrument config additions for grid:
        select_sample_base_kw: dict
            Base kwargs for sample selection command (e.g., {'task_name': 'setPosition'})
        sample_select_kwargs: list[str]
            Keys from grid Dataset to pass to selection command (e.g., ['plate', 'row', 'col'])
    """

    defaults = {}
    # Inherit all defaults from OrchestratorDriver
    defaults.update(OrchestratorDriver.defaults)
    # Add grid-specific defaults
    defaults['grid_file'] = None
    defaults['grid_entry_id'] = None
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
        camera_urls: Optional[List[str]]
            List of camera URLs for snapshots
            
        snapshot_directory: Optional[str]
            Directory for saving snapshots
            
        overrides: Optional[Dict]
            Configuration overrides
        """
        OrchestratorDriver.__init__(
            self,
            camera_urls=camera_urls,
            snapshot_directory=snapshot_directory,
            overrides=overrides
        )

        self.name = 'OrchestratorGridDriver'
        self.grid_sample_count = 0
        self.grid_data = None
        self.stop_grid = False

    def validate_config_grid(self):
        """Validate configuration specific to grid-based sample processing."""
        # Basic client validation
        if not isinstance(self.config['client'], dict):
            raise TypeError("self.config['client'] must be a dictionary")
            
        # Instrument validation - check for grid-specific fields
        if not isinstance(self.config['instrument'], list):
            raise TypeError("self.config['instrument'] must be a list")
        if len(self.config['instrument']) == 0:
            raise ValueError("At least one instrument must be configured in self.config['instrument']")
            
        for i, instrument in enumerate(self.config['instrument']):
            # Check for grid-specific fields if grid is being used
            if self.config.get('grid_entry_id') or self.config.get('grid_file'):
                if 'select_sample_base_kw' not in instrument:
                    raise KeyError(
                        f"Instrument {i} is missing 'select_sample_base_kw' required for grid mode"
                    )
                if 'sample_select_kwargs' not in instrument:
                    raise KeyError(
                        f"Instrument {i} is missing 'sample_select_kwargs' required for grid mode"
                    )
                if not isinstance(instrument['sample_select_kwargs'], list):
                    raise TypeError(
                        f"Instrument {i}: 'sample_select_kwargs' must be a list"
                    )
                    
        # Validate grid-specific configuration items
        if self.config['grid_file'] is not None and not isinstance(self.config['grid_file'], (str, pathlib.Path)):
            raise TypeError("self.config['grid_file'] must be a string or pathlib.Path")
            
        if self.config['grid_entry_id'] is not None and not isinstance(self.config['grid_entry_id'], str):
            raise TypeError("self.config['grid_entry_id'] must be a string")
            
        if self.config['grid_blank_interval'] is not None and not isinstance(self.config['grid_blank_interval'], int):
            raise TypeError("self.config['grid_blank_interval'] must be an integer")
            
        if self.config['grid_blank_sample'] is not None and not isinstance(self.config['grid_blank_sample'], dict):
            raise TypeError("self.config['grid_blank_sample'] must be a dictionary")
            
        print("Grid configuration validation passed successfully.")

    @Driver.unqueued()
    def upload_grid(self, grid_data: xr.Dataset, metadata: Optional[Dict] = None):
        """Upload an xarray grid Dataset to tiled and store the entry_id in config.
        
        Parameters
        ----------
        grid_data : xr.Dataset
            Grid dataset with sample dimension and composition + position variables
        metadata : dict, optional
            Additional metadata to store with the grid entry
            
        Returns
        -------
        str
            The tiled entry_id for the uploaded grid
        """
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            raise ValueError(f"Failed to connect to Tiled: {client.get('message')}")
        
        # Build metadata
        grid_metadata = {
            'type': 'sample_grid',
            'uploaded_at': datetime.datetime.now().isoformat(),
            'num_samples': grid_data.sizes.get('sample', 0),
        }
        if metadata:
            grid_metadata.update(metadata)
        
        # Generate unique entry key
        entry_key = f"grid_{uuid.uuid4()}"
        
        # Write xarray Dataset to tiled
        # Note: write_array writes each variable as a separate array in a container
        client.write_array(grid_data, key=entry_key, metadata=grid_metadata)
        
        # Store entry_id in config
        self.config['grid_entry_id'] = entry_key
        
        if self.app:
            self.app.logger.info(f"Grid uploaded to tiled with entry_id: {entry_key}")
        else:
            print(f"Grid uploaded to tiled with entry_id: {entry_key}")
            
        return entry_key

    @Driver.quickbar(qb={'button_text':'Reset Grid'})
    def reset_grid(self):
        """Reload the grid from tiled entry_id or file and reset grid_sample_count.
        
        Prioritizes grid_entry_id (tiled) over grid_file (local path).
        """
        if self.config.get('grid_entry_id'):
            # Load from tiled
            client = self._get_tiled_client()
            if isinstance(client, dict) and client.get('status') == 'error':
                error_msg = f"Failed to connect to Tiled: {client.get('message')}"
                if self.app:
                    self.app.logger.error(error_msg)
                raise ValueError(error_msg)
            
            entry_id = self.config['grid_entry_id']
            try:
                self.grid_data = client[entry_id].read()
                self.grid_sample_count = 0
                num_samples = self.grid_data.sizes.get('sample', 0)
                if self.app:
                    self.app.logger.info(f"Grid loaded from tiled entry {entry_id}: {num_samples} samples")
                else:
                    print(f"Grid loaded from tiled entry {entry_id}: {num_samples} samples")
            except Exception as e:
                error_msg = f"Failed to load grid from tiled entry {entry_id}: {str(e)}"
                if self.app:
                    self.app.logger.error(error_msg)
                raise ValueError(error_msg)
                
        elif self.config.get('grid_file'):
            # Load from local file
            try:
                self.grid_data = xr.load_dataset(self.config['grid_file'])
                self.grid_sample_count = 0
                num_samples = self.grid_data.sizes.get('sample', 0)
                if self.app:
                    self.app.logger.info(f"Grid loaded from file: {num_samples} samples")
                else:
                    print(f"Grid loaded from file: {num_samples} samples")
            except Exception as e:
                error_msg = f"Failed to load grid from file {self.config['grid_file']}: {str(e)}"
                if self.app:
                    self.app.logger.error(error_msg)
                raise ValueError(error_msg)
        else:
            self.grid_data = None
            self.grid_sample_count = 0
            if self.app:
                self.app.logger.info("No grid configured (no grid_entry_id or grid_file)")
            else:
                print("No grid configured (no grid_entry_id or grid_file)")

    def process_sample_grid(
            self,
            sample: Dict,
            name: Optional[str] = None,
            sample_uuid: Optional[str] = None,
            AL_campaign_name: Optional[str] = None,
            AL_uuid: Optional[str] = None,
            predict_next: bool = False,
            enqueue_next: bool = False,
            reset_grid_flag: bool = False,
    ):
        """Process a sample from a grid of pre-prepared samples.

        Parameters
        ----------
        sample: Dict
            Dictionary containing sample composition (will find closest match in grid)
            
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
            
        reset_grid_flag: bool
            If True, reload the grid before processing
        """
        # Validate config for grid processing
        self.validate_config_grid()

        if reset_grid_flag or self.grid_data is None:
            self.reset_grid()
        
        if self.grid_data is None:
            raise ValueError("No grid data available. Set grid_entry_id or grid_file in config.")
        
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
        
        # Find the closest sample in the grid by euclidean distance
        available = self.grid_data[self.config['components']].to_array('component').transpose(...,'component')
        selected = xr.Dataset(sample).to_array('component')
        dist = (selected - available).pipe(np.square).sum('component')  # no sqrt needed for just min distance
        sample_index = dist.argmin()
        
        # Get the data variables from grid_data and add them individually to sample dict
        grid_sample = self.grid_data.isel(sample=sample_index).reset_coords()
        for var_name in grid_sample.data_vars:
            sample[var_name] = grid_sample[var_name].item()
        self.update_status(f"Found closest sample: index {sample_index.item()}")
        
        # Generate sample name if not provided
        if name is None:
            self.sample_name = f"{self.config['data_tag']}_{self.uuid['sample'][-8:]}"
        else:
            self.sample_name = name
        
        # Measure the sample
        self.measure_grid_sample(sample, name=self.sample_name, empty=False)
        
        # Store composition data (grid sample composition becomes realized composition)
        sample_composition = {}
        for component in self.config['components']:
            if component in sample:
                sample_composition[component] = sample[component]
        
        # Store in data for reference
        self.data['sample_composition_target'] = sample
        self.data['sample_composition_realized'] = sample_composition
        
        # Set sample info on all clients
        sample_data = self.set_sample(
            sample_name=self.sample_name,
            sample_uuid=self.uuid['sample'],
            AL_campaign_name=self.AL_campaign_name,
            AL_uuid=self.uuid['AL'],
            AL_components=self.config.get('AL_components'),
            sample_composition=sample_composition,
        )
        for client_name in self.config['client'].keys():
            self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)
        
        # Update grid data - remove measured sample
        self.grid_data = self.grid_data.drop_isel(sample=sample_index)
        self.grid_sample_count += 1
        
        # Predict next sample if requested
        if predict_next:
            if sample is not None:
                # Note: construct_grid_datasets would be called here if needed for AL
                pass
            self.predict_next_sample()
            
        # Enqueue next sample if requested
        if enqueue_next:
            ag_result = self.get_client('agent').retrieve_obj(uid=self.uuid['agent'])
            next_samples = ag_result.get('next_samples')
            
            if next_samples is not None:
                # Convert next_samples to dict format
                if hasattr(next_samples, 'to_pandas'):
                    new_sample = next_samples.to_pandas().squeeze().to_dict()
                else:
                    new_sample = dict(next_samples)
                
                task = {
                    'task_name': 'process_sample_grid',
                    'sample': new_sample,
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

    def measure_grid_sample(self, sample: Dict, name: str, empty: bool = False):
        """Measure a sample using the grid-based workflow.
        
        This skips the prepare/mix workflow and directly executes grid actions
        to position and measure the pre-prepared sample.

        Parameters
        ----------
        sample: Dict
            Dictionary containing sample coordinates and properties from grid
        name: str
            Sample name for the measurement
        empty: bool
            If True, measure empty cell (blank)
        """
        self.update_status(f"Starting measurement of {name}")
        
        # Set sample information in all clients
        sample_data = self.set_sample(
            sample_name=name,
            sample_uuid=self.uuid['sample'],
            AL_campaign_name=self.AL_campaign_name,
            AL_uuid=self.uuid['AL'],
            AL_components=self.config['AL_components'],
            sample_composition=sample if not empty else None,
        )
        
        for client_name in self.config['client'].keys():
            self.get_client(client_name).enqueue(task_name='set_sample', **sample_data)
        
        # Wait for rinse if needed
        if self.uuid['rinse'] is not None:
            self.update_status(f'Waiting for rinse...')
            self.get_client('load').wait(self.uuid['rinse'], for_history=False)
            self.update_status(f'Rinse done!')
        
        # Measure empty cell first if not already done
        if not empty:
            self.update_status(f'Cell is clean, measuring empty cell scattering...')
            self.measure(name=name, empty=True, wait=True)
        
        # Move to the sample position and measure for each instrument
        for i, instrument in enumerate(self.config['instrument']):
            if not empty:
                # Execute sample selection command using grid position kwargs
                if 'sample_select_kwargs' in instrument and 'select_sample_base_kw' in instrument:
                    self.update_status(f"Moving to sample position for instrument {instrument.get('name', i)}")
                    move_cmd_kwargs = {}
                    # Extract position kwargs from sample dict
                    for key in instrument['sample_select_kwargs']:
                        if key in sample:
                            move_cmd_kwargs[key] = sample[key]
                    # Merge with base kwargs
                    move_cmd_kwargs.update(instrument['select_sample_base_kw'])
                    
                    # Execute move command
                    self.uuid['move'] = self.get_client(instrument['client_name']).enqueue(**move_cmd_kwargs)
                    self.get_client(instrument['client_name']).wait(self.uuid['move'])
                    self.take_snapshot(prefix=f'05-after-position-{instrument.get("name", i)}-{name}')
            
            # Measure on instrument
            self.update_status(f"Measuring sample with {instrument.get('name', instrument['client_name'])}")
            if empty:
                measure_kw = instrument.get('empty_base_kw', {}).copy()
            else:
                measure_kw = instrument.get('measure_base_kw', {}).copy()
            
            if not measure_kw:
                continue  # Skip if no measurement kwargs defined
                
            measure_kw['name'] = name
            
            # Handle sample_env sweeps if configured
            if 'sample_env' in instrument.keys() and not empty:
                params = []
                vals = []
                for param, conds in instrument['sample_env']['move_swept_kw'].items():
                    params.append(param)
                    vals.append(conds)
                conditions = [{i: j for i, j in zip(params, vallist)} for vallist in itertools.product(*vals)]
                
                starting_condition = conditions[0]
                base_sample_name = name
                
                # Collect entry_ids from all sample_env measurements
                entry_ids = []
                
                for j, cond in enumerate(conditions):
                    sample_env_kw = {}
                    sample_env_kw.update(cond)
                    sample_env_kw.update(instrument['sample_env']['move_base_kw'])
                    sample_data = self.set_sample(
                        sample_name=base_sample_name + f'_{str(j).zfill(3)}',
                        sample_uuid=self.uuid['sample'],
                        AL_campaign_name=self.AL_campaign_name,
                        AL_uuid=self.uuid['AL'],
                        AL_components=self.config['AL_components'],
                        sample_composition=sample if not empty else None,
                    )
                    sample_data['sample_env_conditions'] = cond
                    
                    self.get_client(instrument['sample_env']['client_name']).enqueue(task_name='set_sample', **sample_data)
                    self.get_client(instrument['client_name']).enqueue(task_name='set_sample', **sample_data)
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
            else:
                # Simple measurement without sample_env sweep
                self.uuid['measure'] = self.get_client(instrument['client_name']).enqueue(**measure_kw)
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
        
        # Cleanup
        if not empty:
            self.update_status(f'Cleaning up sample {name}...')
            self.uuid['rinse'] = self.get_client('load').enqueue(task_name='rinseCell')
            self.take_snapshot(prefix=f'07-after-measure-{name}')
            
            self.reset_sample_env(wait=False)
        
        self.update_status(f'All done for {name}!')


_DEFAULT_CUSTOM_CONFIG = {
    '_classname': 'AFL.automation.orchestrator.OrchestratorGridDriver.OrchestratorGridDriver',
    'snapshot_directory': '/home/afl642/snaps'
}

_DEFAULT_PORT = 5000

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
