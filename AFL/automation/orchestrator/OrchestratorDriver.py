import itertools
import datetime
import pathlib
import shutil
import traceback
import uuid
from typing import Optional, Dict, List, Any, Tuple
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
from scipy.spatial.distance import cdist

from AFL.automation.APIServer.Client import Client  # type: ignore
from AFL.automation.APIServer.Driver import Driver  # type: ignore
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
            Valid values: 'masses', 'mass_fraction', 'volume_fraction', 'concentration', 'molarity'

        If dict: Per-component format specification. Every prepared component
            must be explicitly listed.
            Example: {"H2O": "masses", "NaCl": "concentration"}
            Keys are component names, values are format strings (same valid values as above)

        Default: 'masses'
    """

    defaults = {}
    defaults['client'] = {}
    defaults['instrument'] = {}
    defaults['ternary'] = False
    defaults['data_tag'] = 'default'
    defaults['components'] = []
    defaults['AL_components'] = []
    defaults['snapshot_directory'] = '/home/nistoroboto'
    defaults['max_sample_transmission'] = 0.6
    defaults['mix_order'] = []
    defaults['camera_urls'] = []
    defaults['snapshot_directory'] = []
    defaults['prepare_volume'] = '1000 ul'
    defaults['empty_prefix'] = 'MT-'
    defaults['composition_format'] = 'masses'
    defaults['next_samples_variable'] = 'next_samples'
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

    def validate_config(self):
        required_keys = [
            'client',
            'instrument',
            'ternary',
            'data_tag',
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
        if not isinstance(self.config['snapshot_directory'], (str, pathlib.Path)):
            raise TypeError("self.config['snapshot_directory'] must be a string or pathlib.Path")
        if not isinstance(self.config['max_sample_transmission'], (int, float)):
            raise TypeError("self.config['max_sample_transmission'] must be a number")

        allowed_formats = {'masses', 'mass_fraction', 'volume_fraction', 'concentration', 'molarity'}
        composition_format = self.config.get('composition_format')
        if isinstance(composition_format, str):
            if composition_format not in allowed_formats:
                raise ValueError(
                    f"Invalid composition_format '{composition_format}'. "
                    f"Allowed formats: {sorted(allowed_formats)}"
                )
        elif isinstance(composition_format, dict):
            for component, fmt in composition_format.items():
                if fmt not in allowed_formats:
                    raise ValueError(
                        f"Invalid format '{fmt}' for component '{component}'. "
                        f"Allowed formats: {sorted(allowed_formats)}"
                    )
        else:
            raise TypeError("self.config['composition_format'] must be a string or dict")

        print("Configuration validation passed successfully.")

    @property
    def tiled_client(self):
        # start tiled catalog connection
        if self.data is None:
            raise ValueError("No DataTiled object added to this class...was it instantiated correctly?")
        return self.data.tiled_client

    def _read_tiled_item(self, item: Any):
        """Read a Tiled item, disabling wide-table optimization when supported."""
        try:
            return item.read(optimize_wide_table=False)
        except TypeError as exc:
            message = str(exc)
            if 'optimize_wide_table' in message or 'unexpected keyword' in message:
                return item.read()
            raise

    def status(self):
        status = []
        status.append(f'Snapshots: {self.config["snapshot_directory"]}')
        status.append(f'Cameras: {self.config["camera_urls"]}')
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
       
        if sample is None:
            sample = {}
        if not isinstance(sample, dict):
            raise TypeError(f"sample must be a dict, got {type(sample).__name__}")

        # Determine whether this request carries an actual composition to prepare.
        composition_keys = (
            'masses', 'volumes', 'concentrations', 'mass_fractions',
            'volume_fractions', 'molarities', 'molalities'
        )
        has_composition = False
        for key in composition_keys:
            if key not in sample:
                continue
            val = sample.get(key)
            if isinstance(val, dict) and len(val) == 0:
                continue
            if val is None:
                continue
            has_composition = True
            break

        if has_composition:
            # Ensure sample has total_volume set
            sample_target = sample.copy()
            if 'total_volume' not in sample_target:
                sample_target['total_volume'] = self.config['prepare_volume']

            # Ensure sample has name set
            if 'name' not in sample_target:
                sample_target['name'] = self.sample_name

            print(f'Sample: {sample_target}')
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
        else:
            self.update_status(
                'No sample composition provided; skipping prep/measurement and running predict/enqueue flow only.'
            )

        if enqueue_next or predict_next:
            self.predict_next_sample()

        # Look away ... here be dragons ...
        if enqueue_next:
            entry_id, entry = self._get_latest_predict_tiled_entry(sample_uuid=self.uuid['sample'])
            new_sample = self._extract_next_sample_from_tiled_entry(
                entry=entry,
                variable_name=self.config['next_samples_variable'],
                entry_id=entry_id,
            )
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

    @staticmethod
    def _get_nested_metadata_value(metadata: Dict[str, Any], path: str) -> Any:
        current: Any = metadata
        for part in path.split('.'):
            if not isinstance(current, dict):
                return None
            if part not in current:
                return None
            current = current[part]
        return current

    @staticmethod
    def _normalize_metadata_value(value: Any) -> Any:
        if isinstance(value, np.generic):
            return value.item()
        return value

    def _iter_metadata_field_values(self, metadata: Any, field_name: str):
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                if key == field_name:
                    yield self._normalize_metadata_value(value)
                yield from self._iter_metadata_field_values(value, field_name)
        elif isinstance(metadata, (list, tuple)):
            for value in metadata:
                yield from self._iter_metadata_field_values(value, field_name)

    def _metadata_matches(
        self,
        metadata: Dict[str, Any],
        expected_value: Any,
        *,
        field_name: str,
        paths: Tuple[str, ...],
    ) -> bool:
        expected_value = self._normalize_metadata_value(expected_value)

        for path in paths:
            value = self._normalize_metadata_value(self._get_nested_metadata_value(metadata, path))
            if value == expected_value:
                return True

        for value in self._iter_metadata_field_values(metadata, field_name):
            if value == expected_value:
                return True

        return False

    def _get_tiled_client_for_lookup(self):
        client = None
        if self.data is not None:
            try:
                client = self.tiled_client
            except Exception:
                client = None

        if client is not None:
            return client

        if 'tiled_uri' not in self.config or not self.config['tiled_uri']:
            return None

        return from_uri(self.config['tiled_uri'], structure_clients="dask")

    def _get_run_documents_container_for_lookup(self, client: Any):
        if client is None:
            return None

        try:
            return client['run_documents']
        except Exception:
            return client

    def _iter_run_document_entries(self, container: Any, prefix: str = ''):
        try:
            items = list(container.items())
        except Exception:
            return

        for key, entry in items:
            entry_id = f'{prefix}/{key}' if prefix else str(key)
            yield entry_id, entry
            yield from self._iter_run_document_entries(entry, prefix=entry_id)

    def _find_run_document_entries(
        self,
        *,
        sample_uuid: str,
        task_name: Optional[str] = None,
    ) -> List[Tuple[str, Any]]:
        client = self._get_tiled_client_for_lookup()
        if client is None:
            self.log_warning("No tiled client available, cannot query run_documents")
            return []

        run_documents = self._get_run_documents_container_for_lookup(client)
        if run_documents is None:
            self.log_warning("No run_documents container found in Tiled")
            return []

        sample_uuid_paths = (
            'sample_uuid',
            'attrs.sample_uuid',
            'attr.sample_uuid',
            'metadata.sample_uuid',
            'metadata.attrs.sample_uuid',
            'metadata.attr.sample_uuid',
        )
        task_name_paths = (
            'task_name',
            'attrs.task_name',
            'attr.task_name',
            'metadata.task_name',
            'metadata.attrs.task_name',
            'metadata.attr.task_name',
        )

        matches: List[Tuple[str, Any]] = []
        for entry_id, entry in self._iter_run_document_entries(run_documents):
            metadata = dict(getattr(entry, 'metadata', {}) or {})
            if not metadata:
                continue

            sample_matches = self._metadata_matches(
                metadata,
                sample_uuid,
                field_name='sample_uuid',
                paths=sample_uuid_paths,
            )
            if not sample_matches:
                continue

            if task_name is not None:
                task_matches = self._metadata_matches(
                    metadata,
                    task_name,
                    field_name='task_name',
                    paths=task_name_paths,
                )
                if not task_matches:
                    continue

            matches.append((entry_id, entry))

        return matches

    def _iter_predict_entries_for_sample(self, sample_uuid: str) -> List[Tuple[str, Any]]:
        """Find predict-task run_documents entries for a sample UUID."""
        candidate_entries = self._find_run_document_entries(
            sample_uuid=sample_uuid,
            task_name='predict',
        )
        if candidate_entries:
            return candidate_entries

        error_msg = (
            f"No predict entries found in run_documents for sample_uuid={sample_uuid}. "
            "Checked metadata values recursively for sample_uuid/task_name, including attrs.* fields."
        )
        self.log_error(error_msg)
        raise ValueError(error_msg)

    @staticmethod
    def _parse_metadata_timestamp(value: Any) -> Optional[datetime.datetime]:
        value = OrchestratorDriver._normalize_metadata_value(value)
        if isinstance(value, datetime.datetime):
            return value
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        for parser in (
            lambda raw: datetime.datetime.fromisoformat(raw.replace('Z', '+00:00')),
            lambda raw: datetime.datetime.strptime(raw, '%m/%d/%y %H:%M:%S-%f'),
            lambda raw: datetime.datetime.strptime(raw, '%Y-%m-%d %H:%M:%S'),
        ):
            try:
                return parser(text)
            except ValueError:
                continue

        return None

    def _entry_sort_timestamp(self, entry: Any) -> datetime.datetime:
        metadata = dict(getattr(entry, 'metadata', {}) or {})
        timestamp_paths = (
            'meta.ended',
            'attrs.meta.ended',
            'attr.meta.ended',
            'metadata.meta.ended',
            'metadata.attrs.meta.ended',
            'metadata.attr.meta.ended',
            'meta.started',
            'attrs.meta.started',
            'attr.meta.started',
            'metadata.meta.started',
            'metadata.attrs.meta.started',
            'metadata.attr.meta.started',
            'timestamp',
            'attrs.timestamp',
            'attr.timestamp',
            'metadata.timestamp',
            'metadata.attrs.timestamp',
            'metadata.attr.timestamp',
        )
        for path in timestamp_paths:
            parsed = self._parse_metadata_timestamp(self._get_nested_metadata_value(metadata, path))
            if parsed is not None:
                return parsed

        for field_name in ('ended', 'started', 'timestamp'):
            for value in self._iter_metadata_field_values(metadata, field_name):
                parsed = self._parse_metadata_timestamp(value)
                if parsed is not None:
                    return parsed
        return datetime.datetime.min

    def _get_latest_predict_tiled_entry(self, sample_uuid: str) -> Tuple[str, Any]:
        entries = self._iter_predict_entries_for_sample(sample_uuid=sample_uuid)
        entries_with_index = list(enumerate(entries))
        latest = max(
            entries_with_index,
            key=lambda indexed: (
                self._entry_sort_timestamp(indexed[1][1]),
                indexed[0],
            )
        )
        return latest[1]

    def _extract_next_sample_from_tiled_entry(self, entry: Any, variable_name: str, entry_id: str) -> Dict[str, Any]:
        try:
            dataset = self._read_tiled_item(entry)
        except Exception as exc:
            error_msg = f"Failed to read tiled predict entry '{entry_id}': {exc}"
            self.app.logger.error(error_msg)
            raise ValueError(error_msg) from exc

        if not isinstance(dataset, xr.Dataset):
            error_msg = (
                f"Predict tiled entry '{entry_id}' did not return an xarray.Dataset "
                f"(got {type(dataset).__name__})."
            )
            self.app.logger.error(error_msg)
            raise ValueError(error_msg)

        if variable_name not in dataset.data_vars:
            error_msg = (
                f"Predict tiled entry '{entry_id}' is missing data variable '{variable_name}'. "
                f"Available variables: {list(dataset.data_vars.keys())}"
            )
            self.app.logger.error(error_msg)
            raise ValueError(error_msg)

        variable = dataset[variable_name]
        extracted = variable.to_pandas().squeeze()
        if isinstance(extracted, dict):
            return extracted
        if hasattr(extracted, 'to_dict'):
            extracted = extracted.to_dict()
        if not isinstance(extracted, dict):
            error_msg = (
                f"Could not convert '{variable_name}' in tiled entry '{entry_id}' to dict; "
                f"got {type(extracted).__name__}."
            )
            self.app.logger.error(error_msg)
            raise ValueError(error_msg)
        return extracted

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

            # Step 4: Get realized composition from prep server in configured format.
            # The prep server has direct access to the balanced Solution objects
            # and the component DB, so it performs the composition math.
            self.update_status(f'Getting realized composition from prep server...')
            composition_format = self.config.get('composition_format', 'masses')
            comp_result = self.get_client('prep').enqueue(
                task_name='get_sample_composition',
                composition_format=composition_format,
                interactive=True
            )

            if not comp_result or comp_result.get('status') == 'failed':
                error_msg = f"Failed to get sample composition for {name}"
                self.update_status(error_msg)
                self.app.logger.error(error_msg)
                return False

            sample_composition = comp_result.get('return_val')
            if not sample_composition:
                error_msg = f"get_sample_composition returned empty for {name}"
                self.update_status(error_msg)
                self.app.logger.error(error_msg)
                return False

            # Also fetch the balance_report for success check and location fallback
            balance_result = self.get_client('prep').enqueue(
                task_name='balance_report',
                interactive=True
            )
            balance_report = balance_result.get('return_val') if balance_result else None
            if balance_report and len(balance_report) > 0:
                last_entry = balance_report[-1]
                balanced_target_dict = last_entry.get('balanced_target')
                if not last_entry.get('success'):
                    error_msg = f"Balance was not successful for {name}"
                    self.update_status(error_msg)
                    self.app.logger.error(error_msg)
                    return False
            else:
                balanced_target_dict = None

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
            elif balanced_target_dict is not None:
                solution_location = balanced_target_dict.get('location')
            else:
                solution_location = None
            
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
            matching_entries = [
                (entry_id, self._entry_sort_timestamp(entry))
                for entry_id, entry in self._find_run_document_entries(
                    sample_uuid=sample_uuid,
                    task_name=task_name,
                )
            ]

            if not matching_entries:
                self.log_warning(
                    f"No tiled entry found for sample_uuid={sample_uuid}, task_name={task_name}"
                )
                return None

            # Sort by timestamp and return the last one
            matching_entries.sort(key=lambda x: (x[1], x[0]), reverse=True)
            return matching_entries[0][0]

        except Exception as e:
            self.log_error(f"Error querying tiled for entry_id: {e}")
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
        agent_client = self.get_client('agent')
        config_result = agent_client.get_config(
            'tiled_input_groups',
            print_console=False,
            interactive=True,
        )
        if (
            isinstance(config_result, dict)
            and config_result.get('exit_state') == 'Error!'
        ):
            raise RuntimeError(
                f"Failed to fetch agent tiled_input_groups: {config_result.get('return_val')}"
            )
        current_groups = config_result.get('return_val') if isinstance(config_result, dict) else config_result

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

        set_result = agent_client.set_config(
            interactive=True,
            tiled_input_groups=current_groups,
        )
        if (
            isinstance(set_result, dict)
            and set_result.get('exit_state') == 'Error!'
        ):
            raise RuntimeError(
                f"Failed to update agent tiled_input_groups: {set_result.get('return_val')}"
            )

_DEFAULT_CUSTOM_CONFIG = {

    '_classname': 'AFL.automation.orchestrator.OrchestratorDriver.OrchestratorDriver',
    'snapshot_directory': '/home/afl642/snaps'
}

_DEFAULT_PORT=5000

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
