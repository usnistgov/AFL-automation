from AFL.automation.shared.utilities import listify
from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared import serialization
from math import ceil, sqrt
import inspect
import json
import pathlib
import uuid

from flask import render_template, jsonify, request
from tiled.client import from_uri

def makeRegistrar():
    functions = []
    decorator_kwargs = {}
    function_info = {}
    def registrarfactory(**kwargs):
        #print(f'Set up registrar-factory with registry {registry}...')
        def registrar(func):#,render_hint=None):  #kwarg = kwargs):
            if func.__name__ not in functions:
                functions.append(func.__name__)
                decorator_kwargs[func.__name__]=kwargs
        
                argspec = inspect.getfullargspec(func)
                if argspec.defaults is None:
                    fargs = argspec.args
                    fkwargs = []
                else:
                    fargs = argspec.args[:-len(argspec.defaults)]
                    fkwargs = [(i,j) for i,j in zip(argspec.args[-len(argspec.defaults):],argspec.defaults)]
                if fargs[0] == 'self':
                    del fargs[0]
                function_info[func.__name__] = {'args':fargs,'kwargs':fkwargs,'doc':func.__doc__}
                if 'qb' in kwargs:
                    function_info[func.__name__]['qb'] = kwargs['qb']
            return func  # normally a decorator returns a wrapped function, 
                         # but here we return func unmodified, after registering it
        return registrar
    registrarfactory.functions = functions
    registrarfactory.decorator_kwargs = decorator_kwargs
    registrarfactory.function_info = function_info
    return registrarfactory


class Driver:
    unqueued = makeRegistrar()
    queued = makeRegistrar()
    quickbar = makeRegistrar()
    # Mapping of url subpaths to filesystem directories containing static assets
    # Example: {'docs': '/path/to/docs', 'assets': pathlib.Path(__file__).parent / 'assets'}
    # Files will be served at /static/{subpath}/{filename}
    static_dirs = {
        "tiled_browser_js": pathlib.Path(__file__).parent.parent / "driver_templates" / "tiled_browser" / "js",
        "tiled_browser_css": pathlib.Path(__file__).parent.parent / "driver_templates" / "tiled_browser" / "css",
    }

    def __init__(self, name, defaults=None, overrides=None, useful_links=None):
        self.app = None
        self.data = None
        self.dropbox = None
        self._tiled_client = None  # Cached Tiled client

        if name is None:
            self.name = 'Driver'
        else:
            self.name = name

        if useful_links is None:
            self.useful_links = {"Tiled Browser": "/tiled_browser"}
        else:
            useful_links["Tiled Browser"] = "/tiled_browser"
            self.useful_links = useful_links

        self.path = pathlib.Path.home() / '.afl'
        self.path.mkdir(exist_ok=True,parents=True)
        self.filepath = self.path / (name + '.config.json')

        self.config = PersistentConfig(
            path=self.filepath,
            defaults= defaults,
            overrides= overrides,
            )

        # collect inherited static directories
        self.static_dirs = self.gather_static_dirs()

    @classmethod
    def gather_defaults(cls):
        '''Gather all inherited static class-level dictionaries called default.'''

        defaults = {}
        for parent in cls.__mro__:
            if hasattr(parent,'defaults'):
                defaults.update(parent.defaults)
        return defaults

    @classmethod
    def gather_static_dirs(cls):
        '''Gather all inherited class-level dictionaries named static_dirs.
        
        This method walks through the Method Resolution Order (MRO) to collect
        static_dirs definitions from all parent classes. Child class definitions
        override parent definitions for the same subpath key.
        
        Returns
        -------
        dict
            Dictionary mapping subpaths to pathlib.Path objects for directories
            containing static files to be served by the API server.
        '''

        dirs = {}
        for parent in cls.__mro__:
            if hasattr(parent, 'static_dirs'):
                dirs.update({k: pathlib.Path(v) for k, v in getattr(parent, 'static_dirs').items()})
        return dirs
    
    def set_config(self,**kwargs):
        self.config.update(kwargs)
        # if ('driver' in kwargs) and (kwargs['driver'] is not None):
        #     driver_name = kwargs['driver']
        #     del kwargs['driver']

        #     try:
        #         driver_obj = getattr(self,driver_name)
        #     except AttributeError:
        #         raise ValueError(f'Driver \'{driver_name}\' not found in protocol \'{self.name}\'')

        #     driver_obj.config.update(kwargs)
        # else:
        #     self.config.update(kwargs)

    def get_config(self,name,print_console=False):
        # if ('driver' in kwargs) and (kwargs['driver'] is not None):
        #     driver_name = kwargs['driver']
        #     del kwargs['driver']

        #     try:
        #         driver_obj = getattr(self,driver_name)
        #     except AttributeError:
        #         raise ValueError(f'Driver \'{driver_name}\' not found in protocol \'{self.name}\'')

        #     value = driver_obj.config[name]
        # else:
        #     value = self.config[name]

        value = self.config[name]
        if print_console:
            print(f'{name:30s} = {value}')

        return value

    def get_configs(self,print_console=False):
        # if driver is not None:
        #     try:
        #         driver_obj = getattr(self,driver_name)
        #     except AttributeError:
        #         raise ValueError(f'Driver \'{driver_name}\' not found in protocol \'{self.name}\'')
        #     config=driver_obj.config
        # else:
        #     config = self.config

        config = self.config
        if print_console:
            for name,value in config:
                print(f'{name:30s} = {value}')
        return config.config
    
    def set_sample(self,sample_name,sample_uuid=None,**kwargs):
        if sample_uuid is None:
            sample_uuid = 'SAM-' + str(uuid.uuid4())

        kwargs.update({'sample_name':sample_name,'sample_uuid':sample_uuid})
        self.data.update(kwargs)

        # update the protected sample keys
        keys = set(self.data.PROTECTED_SAMPLE_KEYS)
        keys.update(kwargs.keys())
        self.data.PROTECTED_SAMPLE_KEYS = list(keys)
        
        return kwargs

    def get_sample(self):
        return self.data._sample_dict

    def reset_sample(self):
        self.data.reset_sample()

    def status(self):
        status = []
        return status

    def pre_execute(self,**kwargs):
        '''Executed before each call to execute

           All of the kwargs passed to execute are also pass to this method. It
           is expected that this method be overridden by subclasses.
        '''
        pass

    def post_execute(self,**kwargs):
        '''Executed after each call to execute

           All of the kwargs passed to execute are also pass to this method. It
           is expected that this method be overridden by subclasses.
        '''
        pass

    def execute(self,**kwargs):
        task_name = kwargs.get('task_name',None)
        if task_name is None:
            raise ValueError('No name field in task. Don\'t know what to execute...')
        del kwargs['task_name']

        if 'device' in kwargs:
            device_name = kwargs['device']
            del kwargs['device']
            try:
                device_obj = getattr(self,device_name)
            except AttributeError:
                raise ValueError(f'Device \'{device_name}\' not found in protocol \'{self.name}\'')

            self.app.logger.info(f'Sending task \'{task_name}\' to device \'{device_name}\'!')
            return_val = getattr(device_obj,task_name)(**kwargs)
        else:
            return_val = getattr(self,task_name)(**kwargs)
        return return_val
    
    def set_object(self,serialized=True,**kw):
        for name,value in kw.items():
            self.app.logger.info(f'Sending object \'{name}\'')
            if serialized:
                value = serialization.deserialize(value)
            setattr(self,name,value)
    
    def get_object(self,name,serialize=True):
        value = getattr(self,name)
        self.app.logger.info(f'Getting object \'{name}\'')
        if serialize:
            value = serialization.serialize(value)
        return value

    def set_data(self,data: dict):
        '''Set data in the DataPacket object

        Parameters
        ----------
        data : dict
            Dictionary of data to store in the driver object
        
        Note! if the keys in data are not system or sample variables,
        they will be erased at the end of this function call.
        

        '''
        for name,value in data.items():
            self.app.logger.info(f'Setting data \'{name}\'')
            self.data.update(data)

    def retrieve_obj(self,uid,delete=True):
        '''Retrieve an object from the dropbox

        Parameters
        ----------
        uid : str
            The uuid of the file to retrieve
        '''
        self.app.logger.info(f'Retrieving file \'{uid}\' from dropbox')
        obj = self.dropbox[uid]
        if delete:
            del self.dropbox[uid]
        return obj
    def deposit_obj(self,obj,uid=None):
        '''Store an object in the dropbox

        Parameters
        ----------
        obj : object
            The object to store in the dropbox
        uid : str
            The uuid to store the object under
        '''
        if uid is None:
            uid = 'DB-' + str(uuid.uuid4())
        if self.dropbox is None:
            self.dropbox = {}
        self.app.logger.info(f'Storing object in dropbox as {uuid}')
        self.dropbox[uid] = obj
        return uid

    @unqueued(render_hint='html')
    def tiled_browser(self, **kwargs):
        """Serve the Tiled database browser HTML interface."""
        return render_template('tiled_browser.html')

    @unqueued(render_hint='html')
    def tiled_plot(self, **kwargs):
        """Serve the Tiled plotting interface for selected entries."""
        return render_template('tiled_plot.html')

    def _read_tiled_config(self):
        """Internal helper to read Tiled config from ~/.afl/config.json.

        Returns:
            dict with status and config values or error message
        """
        config_path = pathlib.Path.home() / '.afl' / 'config.json'

        if not config_path.exists():
            return {
                'status': 'error',
                'message': 'Config file not found at ~/.afl/config.json. Please create this file with tiled_server and tiled_api_key settings.'
            }

        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            return {
                'status': 'error',
                'message': f'Invalid JSON in config file: {str(e)}'
            }

        # Search through config entries (newest first) to find tiled settings
        if not config_data:
            return {
                'status': 'error',
                'message': 'Config file is empty.'
            }

        # Try entries in reverse sorted order to find one with tiled config
        keys = sorted(config_data.keys(), reverse=True)
        tiled_server = ''
        tiled_api_key = ''

        for key in keys:
            entry = config_data[key]
            if isinstance(entry, dict):
                server = entry.get('tiled_server', '')
                api_key = entry.get('tiled_api_key', '')
                if server and api_key:
                    tiled_server = server
                    tiled_api_key = api_key
                    break

        if not tiled_server:
            return {
                'status': 'error',
                'message': 'tiled_server not configured in ~/.afl/config.json. Please add a tiled_server URL to your config.'
            }

        if not tiled_api_key:
            return {
                'status': 'error',
                'message': 'tiled_api_key not configured in ~/.afl/config.json. Please add your Tiled API key to the config.'
            }

        return {
            'status': 'success',
            'tiled_server': tiled_server,
            'tiled_api_key': tiled_api_key
        }

    @unqueued()
    def tiled_config(self, **kwargs):
        """Return Tiled server configuration from shared config file.

        Reads tiled_server and tiled_api_key from ~/.afl/config.json.
        Returns dict with status and config values or helpful error message.
        """
        return self._read_tiled_config()

    def _get_tiled_client(self):
        """Get or create cached Tiled client.

        Returns:
            Tiled client or dict with error status
        """
        if self._tiled_client is not None:
            return self._tiled_client

        # Get config using internal method (avoids decorator issues)
        config = self._read_tiled_config()
        if config['status'] == 'error':
            return config

        try:
            # Create and cache client
            self._tiled_client = from_uri(
                config['tiled_server'],
                api_key=config['tiled_api_key']
            )
            return self._tiled_client
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to connect to Tiled: {str(e)}'
            }

    @unqueued()
    def tiled_search(self, queries='', offset=0, limit=50, **kwargs):
        """Proxy endpoint for Tiled metadata search to avoid CORS issues.

        Args:
            queries: JSON string of query list: [{"field": "field_name", "value": "search_value"}, ...]
            offset: Result offset for pagination
            limit: Number of results to return

        Returns:
            dict with status, data, total_count, or error message
        """
        # Get cached Tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        # Convert offset and limit to integers (they come as strings from URL params)
        offset = int(offset)
        limit = int(limit)

        try:
            # Parse queries JSON
            import json
            if queries and queries != '[]':
                query_list = json.loads(queries) if isinstance(queries, str) else queries
            else:
                query_list = []

            # Start with root client
            results = client

            # Group queries by field to handle multiple values (OR logic)
            if query_list:
                from tiled.queries import Contains, In
                from collections import defaultdict

                # Group values by field
                field_values = defaultdict(list)
                for query_item in query_list:
                    field = query_item.get('field', '')
                    value = query_item.get('value', '')
                    if field and value:
                        field_values[field].append(value)

                # Apply queries - use In for multiple values, Contains for single
                # Search in both metadata and attrs fields and collect unique keys
                all_matching_keys = set()

                for field, values in field_values.items():
                    field_matching_keys = set()

                    if len(values) == 1:
                        # Single value: use Contains
                        try:
                            metadata_results = results.search(Contains(field, values[0]))
                            field_matching_keys.update(metadata_results.keys())
                        except:
                            pass

                        try:
                            attrs_results = results.search(Contains(f'attrs.{field}', values[0]))
                            field_matching_keys.update(attrs_results.keys())
                        except:
                            pass
                    else:
                        # Multiple values: use In
                        try:
                            metadata_results = results.search(In(field, values))
                            field_matching_keys.update(metadata_results.keys())
                        except:
                            pass

                        try:
                            attrs_results = results.search(In(f'attrs.{field}', values))
                            field_matching_keys.update(attrs_results.keys())
                        except:
                            pass

                    # Intersect with previous field results (AND logic between fields)
                    if not all_matching_keys:
                        all_matching_keys = field_matching_keys
                    else:
                        all_matching_keys &= field_matching_keys

            # Get keys to use based on whether we have filters
            if query_list and field_values:
                # Use filtered keys from combined search
                all_keys = sorted(list(all_matching_keys))
                total_count = len(all_keys)
                paginated_keys = all_keys[offset:offset + limit]
                # Use client as results for accessing items
                results = client
            else:
                # No queries - use all keys
                results = client
                total_count = len(results)
                all_keys = list(results.keys())
                paginated_keys = all_keys[offset:offset + limit]

            # Build entries list with metadata
            entries = []
            for key in paginated_keys:
                try:
                    item = results[key]
                    # Build entry in same format as Tiled HTTP API
                    entry = {
                        'id': key,
                        'attributes': {
                            'metadata': dict(item.metadata) if hasattr(item, 'metadata') else {}
                        }
                    }
                    entries.append(entry)
                except Exception as e:
                    # Skip entries that can't be accessed
                    self.app.logger.warning(f'Could not access entry {key}: {str(e)}')
                    continue

            return {
                'status': 'success',
                'data': entries,
                'total_count': total_count
            }

        except Exception as e:
            error_msg = str(e) if str(e) else repr(e)
            self.app.logger.error(f'Tiled search error: {error_msg}', exc_info=True)
            return {
                'status': 'error',
                'message': f'Error searching Tiled database: {error_msg}'
            }

    @unqueued()
    def tiled_get_data(self, entry_id, **kwargs):
        """Proxy endpoint to get xarray HTML representation from Tiled.

        Args:
            entry_id: Tiled entry ID

        Returns:
            dict with status and html, or error message
        """
        # Get cached Tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        try:
            # Get the entry
            if entry_id not in client:
                return {
                    'status': 'error',
                    'message': f'Entry "{entry_id}" not found'
                }

            item = client[entry_id]

            # Try to get xarray dataset representation
            try:
                # Check if this is a DatasetClient and read with optimization
                from tiled.client.xarray import DatasetClient
                if isinstance(item, DatasetClient):
                    dataset = item.read(optimize_wide_table=False)
                else:
                    dataset = item.read()

                # Get HTML representation
                if hasattr(dataset, '_repr_html_'):
                    html = dataset._repr_html_()
                else:
                    # Fallback to string representation
                    html = f'<pre>{str(dataset)}</pre>'

                return {
                    'status': 'success',
                    'html': html
                }
            except Exception as e:
                # If can't read as dataset, provide basic info
                html = '<div class="data-display">'
                html += f'<p><strong>Entry ID:</strong> {entry_id}</p>'
                html += f'<p><strong>Type:</strong> {type(item).__name__}</p>'
                if hasattr(item, 'metadata'):
                    html += '<h4>Metadata:</h4>'
                    html += f'<pre>{json.dumps(dict(item.metadata), indent=2)}</pre>'
                html += f'<p><em>Could not load data representation: {str(e)}</em></p>'
                html += '</div>'

                return {
                    'status': 'success',
                    'html': html
                }

        except KeyError:
            return {
                'status': 'error',
                'message': f'Entry "{entry_id}" not found'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error fetching data: {str(e)}'
            }

    @unqueued()
    def tiled_get_metadata(self, entry_id, **kwargs):
        """Proxy endpoint to get metadata from Tiled.

        Args:
            entry_id: Tiled entry ID

        Returns:
            dict with status and metadata, or error message
        """
        # Get cached Tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        try:
            # Get the entry
            if entry_id not in client:
                return {
                    'status': 'error',
                    'message': f'Entry "{entry_id}" not found'
                }

            item = client[entry_id]

            # Extract metadata
            metadata = dict(item.metadata) if hasattr(item, 'metadata') else {}

            return {
                'status': 'success',
                'metadata': metadata
            }

        except KeyError:
            return {
                'status': 'error',
                'message': f'Entry "{entry_id}" not found'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error fetching metadata: {str(e)}'
            }

    @unqueued()
    def tiled_get_distinct_values(self, field, **kwargs):
        """Get distinct/unique values for a metadata field using Tiled's distinct() method.

        Args:
            field: Metadata field name (e.g., 'sample_name', 'sample_uuid', 'AL_campaign_name', 'AL_uuid')

        Returns:
            dict with status and list of unique values, or error message
        """
        # Get cached Tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        try:
            # Use Tiled's distinct() method to get unique values for this field
            distinct_result = client.distinct(field)

            # Extract the values from the metadata
            # distinct() returns {'metadata': {field: [{'value': ..., 'count': ...}, ...]}}
            if 'metadata' in distinct_result and field in distinct_result['metadata']:
                values_list = distinct_result['metadata'][field]
                # Extract just the 'value' field from each entry
                unique_values = [item['value'] for item in values_list if item.get('value') is not None]
            else:
                unique_values = []

            return {
                'status': 'success',
                'field': field,
                'values': unique_values,
                'count': len(unique_values)
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error getting distinct values for field "{field}": {str(e)}'
            }

    @unqueued()
    def tiled_get_combined_plot_data(self, entry_ids, **kwargs):
        """Get concatenated xarray datasets from multiple Tiled entries.

        Args:
            entry_ids: JSON string array of entry IDs to concatenate

        Returns:
            dict with combined dataset structure ready for plotting
        """
        import json
        import xarray as xr

        # Parse entry_ids from JSON string
        try:
            if isinstance(entry_ids, str):
                entry_ids_list = json.loads(entry_ids)
            else:
                entry_ids_list = entry_ids
        except json.JSONDecodeError as e:
            return {
                'status': 'error',
                'message': f'Invalid JSON in entry_ids parameter: {str(e)}'
            }

        # Get Tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        # Collect datasets
        datasets = []
        skipped_entries = []
        metadata_list = []

        for entry_id in entry_ids_list:
            try:
                if entry_id not in client:
                    skipped_entries.append({
                        'entry_id': entry_id,
                        'reason': 'Not found in Tiled'
                    })
                    continue

                item = client[entry_id]

                # Try to read as dataset
                try:
                    dataset = item.read(optimize_wide_table=False)
                except:
                    dataset = item.read()

                # Check if it's an xarray Dataset
                if hasattr(dataset, 'data_vars'):
                    # Extract metadata
                    metadata = dict(item.metadata) if hasattr(item, 'metadata') else {}
                    metadata_list.append(metadata)

                    # Extract sample_composition from metadata and add as coords
                    if 'sample_composition' in metadata and isinstance(metadata['sample_composition'], dict):
                        sample_comp = metadata['sample_composition']

                        # Create a new dimension for sample_composition
                        comp_names = list(sample_comp.keys())
                        comp_values = [sample_comp[name] for name in comp_names]

                        # Add sample_composition as coordinates
                        for i, comp_name in enumerate(comp_names):
                            coord_name = f'composition_{comp_name}'
                            # Add as a scalar coordinate (will be broadcasted during concat)
                            dataset = dataset.assign_coords({coord_name: comp_values[i]})

                    datasets.append(dataset)
                else:
                    skipped_entries.append({
                        'entry_id': entry_id,
                        'reason': 'Not an xarray.Dataset'
                    })

            except Exception as e:
                skipped_entries.append({
                    'entry_id': entry_id,
                    'reason': f'Error reading: {str(e)}'
                })

        # Check if we have any datasets
        if len(datasets) == 0:
            return {
                'status': 'error',
                'message': 'No xarray.Dataset entries found in selection',
                'skipped_entries': skipped_entries
            }

        # Concatenate datasets along 'index' dimension
        try:
            combined_dataset = xr.concat(datasets, dim='index')

            # Cache the dataset for download endpoint
            self._cached_combined_dataset = combined_dataset
            self._cached_entry_ids = entry_ids_list

        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error concatenating datasets: {str(e)}',
                'skipped_entries': skipped_entries
            }

        # Extract structure for JSON serialization
        try:
            # Get HTML representation of combined dataset
            dataset_html = ''
            try:
                dataset_html = combined_dataset._repr_html_()
            except:
                dataset_html = f'<pre>{str(combined_dataset)}</pre>'

            result = {
                'status': 'success',
                'data_type': 'xarray_dataset',
                'num_datasets': len(datasets),
                'variables': list(combined_dataset.data_vars.keys()),
                'dims': list(combined_dataset.dims.keys()),
                'dim_sizes': {dim: int(size) for dim, size in combined_dataset.dims.items()},
                'coords': {},
                'data': {},
                'hue_dim': 'index',
                'available_legend_vars': [],
                'metadata': metadata_list,
                'skipped_entries': skipped_entries,
                'dataset_html': dataset_html
            }

            # Extract coordinates (limit size)
            for coord_name, coord_data in combined_dataset.coords.items():
                try:
                    if coord_data.size < 100000:
                        result['coords'][coord_name] = coord_data.values.tolist()
                    else:
                        result['coords'][coord_name] = {
                            'error': f'Coordinate too large ({coord_data.size} points)',
                            'shape': list(coord_data.shape)
                        }
                except:
                    result['coords'][coord_name] = {
                        'error': 'Could not serialize coordinate'
                    }

            # Extract data variables (with size limits)
            for var_name in combined_dataset.data_vars.keys():
                var = combined_dataset[var_name]

                # Check if variable has 'index' dimension (suitable for legend)
                if 'index' in var.dims:
                    result['available_legend_vars'].append(var_name)

                # Only include if total size is reasonable (<100k points)
                if var.size < 100000:
                    try:
                        result['data'][var_name] = {
                            'values': var.values.tolist(),
                            'dims': list(var.dims),
                            'shape': list(var.shape),
                            'dtype': str(var.dtype)
                        }
                    except:
                        result['data'][var_name] = {
                            'error': f'Could not serialize variable {var_name}',
                            'dims': list(var.dims),
                            'shape': list(var.shape)
                        }
                else:
                    result['data'][var_name] = {
                        'error': f'Variable too large ({var.size} points)',
                        'dims': list(var.dims),
                        'shape': list(var.shape)
                    }

            return result

        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error extracting dataset structure: {str(e)}'
            }

    @unqueued()
    def tiled_download_combined_dataset(self, entry_ids, **kwargs):
        """Download the concatenated xarray dataset as NetCDF file.

        Args:
            entry_ids: JSON string array of entry IDs (to regenerate dataset if needed)

        Returns:
            NetCDF file download with appropriate headers
        """
        from flask import Response
        import json
        import xarray as xr
        from datetime import datetime
        import io

        # Check if we have a cached dataset with matching entry_ids
        if (hasattr(self, '_cached_combined_dataset') and
            hasattr(self, '_cached_entry_ids')):

            # Parse requested entry_ids
            try:
                if isinstance(entry_ids, str):
                    entry_ids_list = json.loads(entry_ids)
                else:
                    entry_ids_list = entry_ids
            except:
                entry_ids_list = None

            # Check if cache matches
            if entry_ids_list == self._cached_entry_ids:
                combined_dataset = self._cached_combined_dataset
            else:
                # Regenerate dataset
                result = self.tiled_get_combined_plot_data(entry_ids, **kwargs)
                if result['status'] == 'error':
                    return result
                combined_dataset = self._cached_combined_dataset
        else:
            # No cache, generate dataset
            result = self.tiled_get_combined_plot_data(entry_ids, **kwargs)
            if result['status'] == 'error':
                return result
            combined_dataset = self._cached_combined_dataset

        # Serialize to NetCDF
        try:
            # Create in-memory bytes buffer
            buffer = io.BytesIO()
            combined_dataset.to_netcdf(buffer)
            buffer.seek(0)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'combined_dataset_{timestamp}.nc'

            # Return as file download
            return Response(
                buffer.getvalue(),
                mimetype='application/x-netcdf',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': 'application/x-netcdf'
                }
            )

        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error creating NetCDF file: {str(e)}'
            }
