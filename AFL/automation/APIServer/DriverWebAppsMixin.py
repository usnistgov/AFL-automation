import datetime
import json
import pathlib

from flask import render_template
from tiled.client import from_uri


class DriverWebAppsMixin:
    def tiled_browser(self, **kwargs):
        """Serve the Tiled database browser HTML interface."""
        return render_template('tiled_browser.html')

    def tiled_plot(self, **kwargs):
        """Serve the Tiled plotting interface for selected entries."""
        return render_template('tiled_plot.html')

    def tiled_gantt(self, **kwargs):
        """Serve the Tiled Gantt chart interface for selected entries."""
        return render_template('tiled_gantt.html')

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
        except (json.JSONDecodeError, ValueError) as e:
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
        # Use datetime parsing to properly sort date keys (format: YY/DD/MM HH:MM:SS.ffffff)
        datetime_key_format = '%y/%d/%m %H:%M:%S.%f'
        try:
            keys = sorted(
                config_data.keys(),
                key=lambda k: datetime.datetime.strptime(k, datetime_key_format),
                reverse=True
            )
        except ValueError:
            # Fallback to lexicographic sort if datetime parsing fails
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
                api_key=config['tiled_api_key'],
                structure_clients="dask",
            )
            return self._tiled_client
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to connect to Tiled: {str(e)}'
            }

    def _read_tiled_item(self, item):
        """Read a Tiled item, disabling wide-table optimization when supported."""
        try:
            return item.read(optimize_wide_table=False)
        except TypeError as exc:
            # Some non-xarray clients do not accept optimize_wide_table.
            message = str(exc)
            if 'optimize_wide_table' in message or 'unexpected keyword' in message:
                return item.read()
            raise

    def tiled_search(self, queries='', filters='', sort='', fields='', offset=0, limit=50, **kwargs):
        """Proxy endpoint for Tiled metadata search to avoid CORS issues.

        Args:
            queries: JSON string of query list: [{"field": "field_name", "value": "search_value"}, ...]
            filters: JSON string mapping fields to arrays of values
            sort: JSON string sort model list: [{"colId": "field", "sort": "asc|desc"}, ...]
            fields: JSON string list of metadata fields to return
            offset: Result offset for pagination
            limit: Number of results to return

        Returns:
            dict with status, data, total_count, or error message
        """
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        offset = int(offset)
        limit = int(limit)

        def _parse_json_param(value, default):
            if value in (None, '', '[]', '{}'):
                return default
            if isinstance(value, str):
                return json.loads(value)
            return value

        def _get_nested(obj, path):
            current = obj
            for part in path.split('.'):
                if not isinstance(current, dict) or part not in current:
                    return None
                current = current[part]
            return current

        def _set_nested(obj, path, value):
            current = obj
            parts = path.split('.')
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = value

        # Map UI fields to metadata paths for search/sort
        field_path_map = {
            'task_name': 'attrs.task_name',
            'driver_name': 'attrs.driver_name',
            'sample_uuid': 'attrs.sample_uuid',
            'sample_name': 'attrs.sample_name',
            'AL_campaign_name': 'attrs.AL_campaign_name',
            'AL_uuid': 'attrs.AL_uuid',
            'AL_components': 'attrs.AL_components',
            'run_time_minutes': 'attrs.meta.run_time_minutes',
            'meta_started': 'attrs.meta.started',
            'meta_ended': 'attrs.meta.ended',
            'id': 'id',
        }

        default_fields = [
            'task_name',
            'driver_name',
            'sample_uuid',
            'sample_name',
            'AL_campaign_name',
            'AL_uuid',
            'AL_components',
            'meta.started',
            'meta.ended',
            'meta.run_time_minutes',
        ]

        try:
            query_list = _parse_json_param(queries, [])
            filter_map = _parse_json_param(filters, {})
            sort_list = _parse_json_param(sort, [])
            requested_fields = _parse_json_param(fields, default_fields)

            # Normalize filters into query_list entries
            if isinstance(filter_map, dict):
                for field, values in filter_map.items():
                    if isinstance(values, list):
                        for value in values:
                            if value:
                                query_list.append({'field': field, 'value': value})
                    elif values:
                        query_list.append({'field': field, 'value': values})

            results = client

            # Apply search filters
            if query_list:
                from tiled.queries import Contains, In
                from collections import defaultdict

                field_values = defaultdict(list)
                for query_item in query_list:
                    field = query_item.get('field', '')
                    value = query_item.get('value', '')
                    if field and value:
                        field_values[field].append(value)

                for field, values in field_values.items():
                    query_key = field_path_map.get(field, field)
                    if len(values) == 1:
                        results = results.search(Contains(query_key, values[0]))
                    else:
                        results = results.search(In(query_key, values))

            # Apply sorting
            if sort_list:
                sort_items = []
                for item in sort_list:
                    field = item.get('colId') or item.get('field')
                    direction = item.get('sort') or item.get('dir')
                    if not field or direction not in ('asc', 'desc'):
                        continue
                    sort_key = field_path_map.get(field, field)
                    sort_dir = 1 if direction == 'asc' else -1
                    sort_items.append((sort_key, sort_dir))
                if sort_items:
                    results = results.sort(*sort_items)

            total_count = len(results)

            # Page results efficiently via ItemsView slicing
            try:
                items = list(results.items()[offset:offset + limit])
            except Exception:
                # Fallback to keys if items() is unavailable
                keys = list(results.keys()[offset:offset + limit])
                items = [(key, results[key]) for key in keys]

            entries = []
            for key, item in items:
                try:
                    metadata = dict(item.metadata) if hasattr(item, 'metadata') else {}
                    trimmed = {}
                    for field in requested_fields:
                        if not field:
                            continue
                        value = _get_nested(metadata, field)
                        if value is None and not field.startswith('attrs.'):
                            value = _get_nested(metadata, f'attrs.{field}')
                        if value is not None:
                            _set_nested(trimmed, field, value)
                    entry = {
                        'id': key,
                        'attributes': {
                            'metadata': trimmed
                        }
                    }
                    entries.append(entry)
                except Exception as e:
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
                dataset = self._read_tiled_item(item)

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

    def _fetch_single_tiled_entry(self, entry_id):
        """Fetch a single entry from Tiled and extract metadata.

        Parameters
        ----------
        entry_id : str
            Tiled entry ID to fetch

        Returns
        -------
        tuple
            (dataset, metadata_dict) where metadata_dict contains:
            - entry_id: str - The Tiled entry ID
            - sample_name: str - Sample name (from metadata, attrs, or entry_id)
            - sample_uuid: str - Sample UUID (from metadata, attrs, or '')
            - sample_composition: Optional[Dict] - Parsed composition with structure:
                {'components': List[str], 'values': List[float]}

        Raises
        ------
        ValueError
            If Tiled client cannot be obtained
            If entry_id is not found in Tiled
            If dataset cannot be read
        """
        import xarray as xr

        # Get tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            raise ValueError(f"Failed to get tiled client: {client.get('message', 'Unknown error')}")

        if entry_id not in client:
            raise ValueError(f'Entry "{entry_id}" not found in tiled')

        item = client[entry_id]

        # Fetch dataset with wide-table optimization disabled for xarray clients.
        dataset = self._read_tiled_item(item)

        # Extract metadata from tiled item
        tiled_metadata = dict(item.metadata) if hasattr(item, 'metadata') else {}

        # Also check dataset attrs for metadata
        ds_attrs = dict(dataset.attrs) if hasattr(dataset, 'attrs') else {}

        # Build metadata dict, preferring tiled metadata over dataset attrs
        # Include ALL metadata fields for Gantt chart
        metadata = {
            'entry_id': entry_id,
            'sample_name': tiled_metadata.get('sample_name') or ds_attrs.get('sample_name') or entry_id,
            'sample_uuid': tiled_metadata.get('sample_uuid') or ds_attrs.get('sample_uuid') or '',
            'sample_composition': None,
            # Add full metadata for Gantt chart and other uses
            'attrs': tiled_metadata.get('attrs', {}) or ds_attrs.get('attrs', {}),
            'meta': tiled_metadata.get('meta', {}) or tiled_metadata.get('attrs', {}).get('meta', {}) or ds_attrs.get('meta', {}),
            'AL_campaign_name': tiled_metadata.get('AL_campaign_name') or tiled_metadata.get('attrs', {}).get('AL_campaign_name') or ds_attrs.get('AL_campaign_name', ''),
            'AL_uuid': tiled_metadata.get('AL_uuid') or tiled_metadata.get('attrs', {}).get('AL_uuid') or ds_attrs.get('AL_uuid', ''),
            'task_name': tiled_metadata.get('task_name') or tiled_metadata.get('attrs', {}).get('task_name') or ds_attrs.get('task_name', ''),
            'driver_name': tiled_metadata.get('driver_name') or tiled_metadata.get('attrs', {}).get('driver_name') or ds_attrs.get('driver_name', ''),
        }

        # Extract sample_composition - be fault tolerant if it doesn't exist
        comp_dict = tiled_metadata.get('sample_composition') or ds_attrs.get('sample_composition')
        if comp_dict and isinstance(comp_dict, dict):
            # Parse composition dict to extract components and values
            components = []
            values = []
            for comp_name, comp_data in comp_dict.items():
                # Skip non-component keys like 'units', 'components', etc.
                if comp_name in ('units', 'conc_units', 'mass_units', 'components'):
                    continue

                try:
                    if isinstance(comp_data, dict):
                        # Handle both 'value' (scalar) and 'values' (array) cases
                        if 'value' in comp_data:
                            values.append(float(comp_data['value']))
                            components.append(comp_name)
                        elif 'values' in comp_data:
                            val = comp_data['values']
                            if isinstance(val, (list, tuple)) and len(val) > 0:
                                values.append(float(val[0]))
                            else:
                                values.append(float(val) if val is not None else 0.0)
                            components.append(comp_name)
                    elif isinstance(comp_data, (int, float)):
                        # Direct numeric value
                        values.append(float(comp_data))
                        components.append(comp_name)
                except (ValueError, TypeError):
                    # Skip components that can't be converted to float
                    continue

            if components:
                metadata['sample_composition'] = {
                    'components': components,
                    'values': values
                }

        return dataset, metadata

    def _detect_sample_dimension(self, dataset, allow_size_fallback=True):
        """Detect the sample dimension from a dataset.
        
        Looks for dimensions matching patterns like '*_sample' or 'sample'.
        Optionally falls back to the first dimension with size > 1.
        
        Parameters
        ----------
        dataset : xr.Dataset
            Dataset to inspect.
        allow_size_fallback : bool, default=True
            If True, use the first dimension with size > 1 when no explicit
            sample-like dimension name is found. If False, return None when no
            explicit sample-like dimension name is present.

        Returns
        -------
        str or None
            The detected sample dimension name, or None if not found
        """
        import re
        
        # Pattern priority: exact 'sample', then '*_sample', then first multi-valued dim
        dims = list(dataset.sizes.keys())
        
        # Check for exact 'sample' first
        if 'sample' in dims:
            return 'sample'
        
        # Check for *_sample pattern
        sample_pattern = re.compile(r'.*_sample$')
        for dim in dims:
            if sample_pattern.match(dim):
                return dim
        
        if allow_size_fallback:
            # Fallback: first dimension with size > 1
            for dim in dims:
                if dataset.sizes[dim] > 1:
                    return dim

            # Last resort: first dimension
            return dims[0] if dims else None
        return None

    def tiled_concat_datasets(self, entry_ids, concat_dim='index', variable_prefix=''):
        """Gather datasets from Tiled entries and concatenate them along a dimension.

        This method fetches multiple datasets from a Tiled server, extracts metadata
        (sample_name, sample_uuid, sample_composition), and concatenates them along
        the specified dimension. It also supports prefixing variable names.

        For a single entry, the dataset is returned as-is without concatenation,
        and the sample dimension is auto-detected from existing dimensions.

        Parameters
        ----------
        entry_ids : List[str]
            List of Tiled entry IDs to fetch and concatenate
        concat_dim : str, default="index"
            Dimension name along which to concatenate the datasets (ignored for single entry)
        variable_prefix : str, default=""
            Optional prefix to prepend to variable, coordinate, and dimension names
            (except the concat_dim itself)

        Returns
        -------
        xr.Dataset
            For single entry: The original dataset with metadata added as attributes
            For multiple entries: Concatenated dataset with:
            - All original data variables and coordinates from individual datasets
            - Additional coordinates along concat_dim:
                - sample_name: Sample name from metadata or entry_id
                - sample_uuid: Sample UUID from metadata or empty string
                - entry_id: The Tiled entry ID for each dataset
            - If sample_composition metadata exists:
                - composition: DataArray with dims [concat_dim, "components"]
                  containing composition values for each sample

        Raises
        ------
        ValueError
            If entry_ids is empty
            If any entry_id is not found in Tiled
            If datasets cannot be fetched or concatenated
        """
        import xarray as xr
        import numpy as np

        if not entry_ids:
            raise ValueError("entry_ids list cannot be empty")

        # Fetch all entry datasets and metadata
        datasets = []
        metadata_list = []
        for entry_id in entry_ids:
            try:
                ds, metadata = self._fetch_single_tiled_entry(entry_id)
                datasets.append(ds)
                metadata_list.append(metadata)
            except Exception as e:
                raise ValueError(f"Failed to fetch entry '{entry_id}': {str(e)}")

        if not datasets:
            raise ValueError("No datasets fetched")

        # SINGLE ENTRY CASE: Return dataset as-is with metadata added
        if len(datasets) == 1:
            dataset = datasets[0]
            metadata = metadata_list[0]
            
            # Detect the sample dimension from the dataset
            # For single entries, avoid guessing a random axis as "sample".
            sample_dim = self._detect_sample_dimension(dataset, allow_size_fallback=False)
            
            # Add metadata as dataset attributes (not coordinates, since we don't have a new dim)
            dataset.attrs['sample_name'] = metadata['sample_name']
            dataset.attrs['sample_uuid'] = metadata['sample_uuid']
            dataset.attrs['entry_id'] = metadata['entry_id']
            dataset.attrs['_detected_sample_dim'] = sample_dim
            
            # If sample_composition exists, add it as a DataArray along the sample dimension
            if metadata['sample_composition'] and sample_dim:
                components = metadata['sample_composition']['components']
                values = metadata['sample_composition']['values']
                
                # Check if composition already exists in dataset (common case)
                # If not, we could add it, but for single entry this is usually already there
                if 'composition' not in dataset.data_vars:
                    # Create composition array - but we need to match the sample dimension size
                    # This is tricky for single entry since composition is per-sample
                    # For now, store in attrs
                    dataset.attrs['sample_composition'] = {
                        'components': components,
                        'values': values
                    }
            
            # Apply variable prefix if specified
            if variable_prefix:
                rename_dict = {}
                for var_name in list(dataset.data_vars):
                    if not var_name.startswith(variable_prefix):
                        rename_dict[var_name] = variable_prefix + var_name
                for coord_name in list(dataset.coords):
                    if coord_name not in dataset.dims and not coord_name.startswith(variable_prefix):
                        rename_dict[coord_name] = variable_prefix + coord_name
                for dim_name in list(dataset.dims):
                    if not dim_name.startswith(variable_prefix):
                        rename_dict[dim_name] = variable_prefix + dim_name
                if rename_dict:
                    dataset = dataset.rename(rename_dict)
            
            return dataset

        # MULTIPLE ENTRIES CASE: Concatenate along concat_dim
        # Collect metadata values for each entry
        sample_names = [m['sample_name'] for m in metadata_list]
        sample_uuids = [m['sample_uuid'] for m in metadata_list]
        entry_id_values = [m['entry_id'] for m in metadata_list]

        # Build compositions DataArray before concatenation
        # Collect all unique components across all entries
        all_components = set()
        for m in metadata_list:
            if m['sample_composition']:
                all_components.update(m['sample_composition']['components'])
        all_components = sorted(list(all_components))

        # Create composition data array if we have components
        if all_components:
            n_samples = len(datasets)
            n_components = len(all_components)
            comp_data = np.zeros((n_samples, n_components))

            for i, m in enumerate(metadata_list):
                if m['sample_composition']:
                    for j, comp_name in enumerate(all_components):
                        if comp_name in m['sample_composition']['components']:
                            idx = m['sample_composition']['components'].index(comp_name)
                            comp_data[i, j] = m['sample_composition']['values'][idx]

            # Create the compositions DataArray
            compositions = xr.DataArray(
                data=comp_data,
                dims=[concat_dim, "components"],
                coords={
                    concat_dim: range(n_samples),
                    "components": all_components
                },
                name="composition"
            )
        else:
            compositions = None

        # Concatenate along new dimension
        # Use coords="minimal" to avoid conflict with compat="override"
        concatenated = xr.concat(datasets, dim=concat_dim, coords="minimal", compat='override')

        # Assign 1D coordinates along concat_dim
        concatenated = concatenated.assign_coords({
            'sample_name': (concat_dim, sample_names),
            'sample_uuid': (concat_dim, sample_uuids),
            'entry_id': (concat_dim, entry_id_values)
        })

        # Add compositions if we have it
        if compositions is not None:
            concatenated = concatenated.assign(composition=compositions)

        # Prefix names (data vars, coords, dims) but NOT the concat_dim itself
        if variable_prefix:
            rename_dict = {}

            # Rename data variables
            for var_name in list(concatenated.data_vars):
                if not var_name.startswith(variable_prefix):
                    rename_dict[var_name] = variable_prefix + var_name

            # Rename coordinates (but not concat_dim)
            for coord_name in list(concatenated.coords):
                if coord_name == concat_dim:
                    continue  # Don't rename the concat_dim coordinate
                if coord_name not in concatenated.dims:  # Non-dimension coordinates
                    if not coord_name.startswith(variable_prefix):
                        rename_dict[coord_name] = variable_prefix + coord_name

            # Rename dimensions but NOT concat_dim
            for dim_name in list(concatenated.dims):
                if dim_name == concat_dim:
                    continue  # Don't rename the concat_dim
                if not dim_name.startswith(variable_prefix):
                    rename_dict[dim_name] = variable_prefix + dim_name

            # Apply all renames
            if rename_dict:
                concatenated = concatenated.rename(rename_dict)

        return concatenated

    def _parse_entry_ids_param(self, entry_ids):
        """Parse entry_ids parameter from JSON string or list."""
        if isinstance(entry_ids, str):
            parsed = json.loads(entry_ids)
        else:
            parsed = entry_ids
        if not isinstance(parsed, list):
            raise ValueError('entry_ids must be a JSON array or list')
        return parsed

    def _entry_ids_cache_key(self, entry_ids_list):
        """Create a stable cache key from ordered entry IDs."""
        return json.dumps(entry_ids_list, separators=(',', ':'))

    def _cache_put(self, cache, order, key, value, max_items):
        """Put value into bounded insertion-ordered cache."""
        if key in cache:
            cache[key] = value
            if key in order:
                order.remove(key)
            order.append(key)
            return

        cache[key] = value
        order.append(key)
        while len(order) > max_items:
            old_key = order.pop(0)
            cache.pop(old_key, None)

    def _get_or_create_combined_dataset(self, entry_ids_list):
        """Get combined dataset from cache or create and cache it."""
        key = self._entry_ids_cache_key(entry_ids_list)
        cached = self._combined_dataset_cache.get(key)
        if cached is not None:
            return cached

        combined_dataset = self.tiled_concat_datasets(
            entry_ids=entry_ids_list,
            concat_dim='index',
            variable_prefix=''
        )
        self._cache_put(
            self._combined_dataset_cache,
            self._combined_dataset_cache_order,
            key,
            combined_dataset,
            self._max_combined_dataset_cache
        )

        # Keep legacy cache fields for existing download flow.
        self._cached_combined_dataset = combined_dataset
        self._cached_entry_ids = entry_ids_list
        return combined_dataset

    def _sanitize_for_json(self, obj):
        """Recursively replace NaN/Inf with None for JSON compatibility."""
        import math
        if isinstance(obj, list):
            return [self._sanitize_for_json(x) for x in obj]
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        return obj

    def _safe_tolist(self, arr):
        """Convert numpy array to JSON-serializable list."""
        import numpy as np
        import pandas as pd

        if not isinstance(arr, np.ndarray):
            arr = np.asarray(arr)

        if np.issubdtype(arr.dtype, np.datetime64):
            return pd.to_datetime(arr).astype(str).tolist()

        if np.issubdtype(arr.dtype, np.timedelta64):
            return (arr / np.timedelta64(1, 's')).tolist()

        return self._sanitize_for_json(arr.tolist())

    def tiled_get_plot_manifest(self, entry_ids, **kwargs):
        """Return lightweight plotting manifest without eager data materialization."""
        try:
            entry_ids_list = self._parse_entry_ids_param(entry_ids)
        except (json.JSONDecodeError, ValueError) as e:
            return {
                'status': 'error',
                'message': f'Invalid JSON in entry_ids parameter: {str(e)}'
            }

        if not entry_ids_list:
            return {
                'status': 'error',
                'message': 'entry_ids must contain at least one entry'
            }

        try:
            combined_dataset = self._get_or_create_combined_dataset(entry_ids_list)
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error concatenating datasets: {str(e)}'
            }

        try:
            is_single_entry = len(entry_ids_list) == 1
            if is_single_entry:
                sample_dim = combined_dataset.attrs.get('_detected_sample_dim', None)
                if not sample_dim:
                    sample_dim = self._detect_sample_dimension(combined_dataset, allow_size_fallback=False)
                num_datasets = int(combined_dataset.dims.get(sample_dim, 1)) if sample_dim else 1
            else:
                sample_dim = 'index'
                num_datasets = int(combined_dataset.dims.get('index', 0))

            dataset_html = ''
            try:
                dataset_html = combined_dataset._repr_html_()
            except Exception:
                dataset_html = f'<pre>{str(combined_dataset)}</pre>'

            coords_preview = {}
            max_coord_preview_size = int(kwargs.get('max_coord_preview_size', 5000))
            for coord_name, coord_data in combined_dataset.coords.items():
                try:
                    if coord_data.ndim == 1 and coord_data.size <= max_coord_preview_size:
                        coords_preview[coord_name] = self._safe_tolist(coord_data.values)
                    else:
                        coords_preview[coord_name] = {
                            'summary': True,
                            'shape': list(coord_data.shape),
                            'dtype': str(coord_data.dtype),
                            'size': int(coord_data.size),
                        }
                except Exception as e:
                    coords_preview[coord_name] = {
                        'error': f'Could not summarize coordinate: {str(e)}'
                    }

            variable_info = {}
            variables = []
            available_legend_vars = []
            for var_name, var in combined_dataset.data_vars.items():
                dims = list(var.dims)
                shape = [int(x) for x in var.shape]
                size = int(var.size)
                dtype = str(var.dtype)

                if sample_dim and sample_dim in dims:
                    available_legend_vars.append(var_name)

                category_hint = 'other'
                if sample_dim and len(dims) == 1 and dims[0] == sample_dim:
                    category_hint = 'sample'
                elif sample_dim and sample_dim in dims and len(dims) >= 2:
                    other_dims = [d for d in dims if d != sample_dim]
                    if other_dims:
                        other_size = int(combined_dataset.dims.get(other_dims[0], 0))
                        category_hint = 'composition' if other_size < 10 else 'scattering'

                variable_info[var_name] = {
                    'name': var_name,
                    'dims': dims,
                    'shape': shape,
                    'size': size,
                    'dtype': dtype,
                    'category_hint': category_hint,
                }
                variables.append(var_name)

            metadata_list = []
            for i, entry_id in enumerate(entry_ids_list):
                sample_name = ''
                sample_uuid = ''
                if 'sample_name' in combined_dataset.coords and i < combined_dataset.coords['sample_name'].size:
                    sample_name = str(combined_dataset.coords['sample_name'].values[i])
                elif i == 0:
                    sample_name = str(combined_dataset.attrs.get('sample_name', ''))
                if 'sample_uuid' in combined_dataset.coords and i < combined_dataset.coords['sample_uuid'].size:
                    sample_uuid = str(combined_dataset.coords['sample_uuid'].values[i])
                elif i == 0:
                    sample_uuid = str(combined_dataset.attrs.get('sample_uuid', ''))
                metadata_list.append({
                    'entry_id': entry_id,
                    'sample_name': sample_name,
                    'sample_uuid': sample_uuid,
                })

            return {
                'status': 'success',
                'data_type': 'xarray_dataset_manifest',
                'num_datasets': num_datasets,
                'variables': variables,
                'variable_info': variable_info,
                'dims': list(combined_dataset.dims.keys()),
                'dim_sizes': {dim: int(size) for dim, size in combined_dataset.dims.items()},
                'coords': coords_preview,
                'data': {},
                'sample_dim': sample_dim,
                'hue_dim': sample_dim or 'index',
                'available_legend_vars': available_legend_vars,
                'metadata': metadata_list,
                'dataset_html': dataset_html,
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error building plot manifest: {str(e)}'
            }

    def tiled_get_plot_variable_data(self, entry_ids, var_name, cast_float32='true', **kwargs):
        """Return one variable payload for plotting, fetched lazily."""
        try:
            entry_ids_list = self._parse_entry_ids_param(entry_ids)
        except (json.JSONDecodeError, ValueError) as e:
            return {
                'status': 'error',
                'message': f'Invalid JSON in entry_ids parameter: {str(e)}'
            }

        if not entry_ids_list:
            return {
                'status': 'error',
                'message': 'entry_ids must contain at least one entry'
            }

        try:
            cast_float32_bool = str(cast_float32).lower() not in ('0', 'false', 'no', 'off')
            max_points = int(kwargs.get('max_points', 2_000_000))
            max_coord_preview_size = int(kwargs.get('max_coord_preview_size', 100000))

            dataset_key = self._entry_ids_cache_key(entry_ids_list)
            payload_key = f'{dataset_key}|{var_name}|{int(cast_float32_bool)}'
            cached_payload = self._plot_variable_payload_cache.get(payload_key)
            if cached_payload is not None:
                return cached_payload

            combined_dataset = self._get_or_create_combined_dataset(entry_ids_list)
            if var_name not in combined_dataset.data_vars:
                return {
                    'status': 'error',
                    'message': f'Variable "{var_name}" not found',
                    'available_variables': list(combined_dataset.data_vars.keys())
                }

            var = combined_dataset[var_name]
            if int(var.size) > max_points:
                return {
                    'status': 'error',
                    'message': f'Variable too large ({int(var.size)} points), exceeds max_points={max_points}',
                    'var_name': var_name,
                    'dims': list(var.dims),
                    'shape': list(var.shape),
                    'dtype': str(var.dtype),
                }

            # Pull only this selected variable.
            materialized = var.values
            if cast_float32_bool and hasattr(materialized, 'dtype'):
                import numpy as np
                if np.issubdtype(materialized.dtype, np.floating):
                    materialized = materialized.astype(np.float32, copy=False)

            related_coords = {}
            for dim_name in var.dims:
                if dim_name in combined_dataset.coords:
                    coord = combined_dataset.coords[dim_name]
                    if coord.ndim == 1 and coord.size <= max_coord_preview_size:
                        related_coords[dim_name] = self._safe_tolist(coord.values)
                    else:
                        related_coords[dim_name] = {
                            'summary': True,
                            'shape': list(coord.shape),
                            'dtype': str(coord.dtype),
                            'size': int(coord.size),
                        }

            payload = {
                'status': 'success',
                'var_name': var_name,
                'dims': list(var.dims),
                'shape': [int(x) for x in var.shape],
                'dtype': str(getattr(materialized, 'dtype', var.dtype)),
                'values': self._safe_tolist(materialized),
                'related_coords': related_coords,
            }
            self._cache_put(
                self._plot_variable_payload_cache,
                self._plot_variable_payload_cache_order,
                payload_key,
                payload,
                self._max_variable_payload_cache
            )
            return payload
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error fetching variable data: {str(e)}',
                'var_name': var_name
            }

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
        except (json.JSONDecodeError, ValueError) as e:
            return {
                'status': 'error',
                'message': f'Invalid JSON in entry_ids parameter: {str(e)}'
            }

        # Use the new tiled_concat_datasets method
        skipped_entries = []
        try:
            combined_dataset = self.tiled_concat_datasets(
                entry_ids=entry_ids_list,
                concat_dim='index',
                variable_prefix=''
            )

            # Cache the dataset for download endpoint
            self._cached_combined_dataset = combined_dataset
            self._cached_entry_ids = entry_ids_list

        except ValueError as e:
            # Handle individual entry errors by tracking skipped entries
            error_msg = str(e)
            if 'Failed to fetch entry' in error_msg:
                # Extract entry_id from error message if possible
                import re
                match = re.search(r"Failed to fetch entry '([^']+)'", error_msg)
                if match:
                    skipped_entries.append({
                        'entry_id': match.group(1),
                        'reason': error_msg
                    })

            return {
                'status': 'error',
                'message': f'Error concatenating datasets: {error_msg}',
                'skipped_entries': skipped_entries
            }
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

            # Detect sample dimension:
            # - For single entry: use '_detected_sample_dim' from attrs
            # - For multiple entries: use 'index' (the concat_dim)
            is_single_entry = len(entry_ids_list) == 1
            if is_single_entry:
                sample_dim = combined_dataset.attrs.get('_detected_sample_dim', None)
                if not sample_dim:
                    # Fallback detection
                    sample_dim = self._detect_sample_dimension(combined_dataset, allow_size_fallback=False)
                num_datasets = combined_dataset.dims.get(sample_dim, 1) if sample_dim else 1
            else:
                sample_dim = 'index'
                num_datasets = combined_dataset.dims.get('index', 0)

            # Build metadata list - need to re-fetch metadata for each entry to get full details
            metadata_list = []
            for entry_id in entry_ids_list:
                try:
                    # Re-fetch metadata from Tiled for this specific entry
                    client = self._get_tiled_client()
                    if isinstance(client, dict) and client.get('status') == 'error':
                        # If client fails, use basic metadata
                        metadata_list.append({
                            'entry_id': entry_id,
                            'sample_name': '',
                            'sample_uuid': '',
                            'meta': {},
                            'AL_campaign_name': '',
                        })
                        continue

                    if entry_id not in client:
                        metadata_list.append({
                            'entry_id': entry_id,
                            'sample_name': '',
                            'sample_uuid': '',
                            'meta': {},
                            'AL_campaign_name': '',
                        })
                        continue

                    item = client[entry_id]
                    tiled_metadata = dict(item.metadata) if hasattr(item, 'metadata') else {}

                    # Extract full metadata including timing data
                    metadata_list.append({
                        'entry_id': entry_id,
                        'sample_name': tiled_metadata.get('sample_name', ''),
                        'sample_uuid': tiled_metadata.get('sample_uuid', ''),
                        'AL_campaign_name': tiled_metadata.get('AL_campaign_name') or tiled_metadata.get('attrs', {}).get('AL_campaign_name', ''),
                        'AL_uuid': tiled_metadata.get('AL_uuid') or tiled_metadata.get('attrs', {}).get('AL_uuid', ''),
                        'task_name': tiled_metadata.get('task_name') or tiled_metadata.get('attrs', {}).get('task_name', ''),
                        'driver_name': tiled_metadata.get('driver_name') or tiled_metadata.get('attrs', {}).get('driver_name', ''),
                        'meta': tiled_metadata.get('meta', {}) or tiled_metadata.get('attrs', {}).get('meta', {}),
                    })
                except Exception as e:
                    # If metadata fetch fails for an entry, use basic metadata
                    metadata_list.append({
                        'entry_id': entry_id,
                        'sample_name': '',
                        'sample_uuid': '',
                        'meta': {},
                        'AL_campaign_name': '',
                    })

            result = {
                'status': 'success',
                'data_type': 'xarray_dataset',
                'num_datasets': num_datasets,
                'variables': list(combined_dataset.data_vars.keys()),
                'dims': list(combined_dataset.dims.keys()),
                'dim_sizes': {dim: int(size) for dim, size in combined_dataset.dims.items()},
                'coords': {},
                'data': {},
                'sample_dim': sample_dim,  # Tell the client which dimension is the sample dimension
                'hue_dim': sample_dim or 'index',  # Use detected sample_dim as hue_dim
                'available_legend_vars': [],
                'metadata': metadata_list,
                'skipped_entries': skipped_entries,
                'dataset_html': dataset_html
            }

            # Helper function to recursively sanitize values for JSON
            def sanitize_for_json(obj):
                """Recursively replace NaN and Inf with None for JSON compatibility."""
                import numpy as np
                import math
                if isinstance(obj, list):
                    return [sanitize_for_json(x) for x in obj]
                elif isinstance(obj, float):
                    if math.isnan(obj) or math.isinf(obj):
                        return None
                    return obj
                else:
                    return obj

            # Helper function to safely convert numpy arrays to JSON-serializable lists
            def safe_tolist(arr):
                """Convert numpy array to list, handling NaN, Inf, and datetime objects."""
                import numpy as np
                import pandas as pd

                # Convert to numpy array if not already
                if not isinstance(arr, np.ndarray):
                    arr = np.asarray(arr)

                # Handle datetime types
                if np.issubdtype(arr.dtype, np.datetime64):
                    # Convert to ISO format strings
                    return pd.to_datetime(arr).astype(str).tolist()

                # Handle timedelta types
                if np.issubdtype(arr.dtype, np.timedelta64):
                    # Convert to total seconds
                    return (arr / np.timedelta64(1, 's')).tolist()

                # Convert to list
                lst = arr.tolist()

                # Recursively replace NaN and Inf with None for JSON compatibility
                return sanitize_for_json(lst)

            # Extract coordinates (limit size)
            print(f"\n=== EXTRACTING COORDINATES ===")
            for coord_name, coord_data in combined_dataset.coords.items():
                try:
                    print(f"Coordinate: {coord_name}, dtype: {coord_data.dtype}, size: {coord_data.size}, shape: {coord_data.shape}")
                    if coord_data.size < 100000:
                        converted = safe_tolist(coord_data.values)
                        result['coords'][coord_name] = converted
                        print(f"  ✓ Converted: type={type(converted).__name__}, sample={str(converted)[:100] if converted else 'None'}")
                    else:
                        result['coords'][coord_name] = {
                            'error': f'Coordinate too large ({coord_data.size} points)',
                            'shape': list(coord_data.shape)
                        }
                        print(f"  ⊘ Skipped: too large")
                except Exception as e:
                    print(f"  ✗ ERROR: {type(e).__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    result['coords'][coord_name] = {
                        'error': f'Could not serialize coordinate: {str(e)}'
                    }

            # Extract data variables (with size limits)
            print(f"\n=== EXTRACTING DATA VARIABLES ===")
            for var_name in combined_dataset.data_vars.keys():
                var = combined_dataset[var_name]

                # Check if variable has sample dimension (suitable for legend)
                if sample_dim and sample_dim in var.dims:
                    result['available_legend_vars'].append(var_name)

                # Only include if total size is reasonable (<100k points)
                print(f"Variable: {var_name}, dtype: {var.dtype}, size: {var.size}, shape: {var.shape}, dims: {var.dims}")
                if var.size < 100000:
                    try:
                        converted = safe_tolist(var.values)
                        result['data'][var_name] = {
                            'values': converted,
                            'dims': list(var.dims),
                            'shape': list(var.shape),
                            'dtype': str(var.dtype)
                        }
                        print(f"  ✓ Converted: type={type(converted).__name__}, sample={str(converted)[:100] if converted else 'None'}")
                    except Exception as e:
                        print(f"  ✗ ERROR: {type(e).__name__}: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        result['data'][var_name] = {
                            'error': f'Could not serialize variable {var_name}: {str(e)}',
                            'dims': list(var.dims),
                            'shape': list(var.shape)
                        }
                else:
                    result['data'][var_name] = {
                        'error': f'Variable too large ({var.size} points)',
                        'dims': list(var.dims),
                        'shape': list(var.shape)
                    }
                    print(f"  ⊘ Skipped: too large")

            # Test JSON serialization before returning
            print(f"\n=== TESTING JSON SERIALIZATION ===")
            try:
                import json
                json_str = json.dumps(result)
                print(f"✓ JSON serialization successful, length: {len(json_str)} chars")
            except Exception as json_err:
                print(f"✗ JSON serialization FAILED: {type(json_err).__name__}: {str(json_err)}")
                # Try to find which field is problematic
                for key in ['coords', 'data']:
                    if key in result:
                        print(f"\nTesting '{key}' field:")
                        for subkey, subval in result[key].items():
                            try:
                                json.dumps({subkey: subval})
                                print(f"  ✓ {subkey}: OK")
                            except Exception as e:
                                print(f"  ✗ {subkey}: FAILED - {type(e).__name__}: {str(e)}")
                                print(f"    Type: {type(subval)}, Sample: {str(subval)[:200]}")

            return result

        except Exception as e:
            print(f"\n✗ EXCEPTION in tiled_get_combined_plot_data: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'message': f'Error extracting dataset structure: {str(e)}'
            }

    def tiled_get_gantt_metadata(self, entry_ids, **kwargs):
        """Get metadata for Gantt chart from multiple Tiled entries.

        This is a lightweight endpoint that only fetches metadata without
        loading or combining the actual datasets.

        Args:
            entry_ids: JSON string array of entry IDs

        Returns:
            dict with list of metadata for each entry
        """
        import json

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

        # Get tiled client
        client = self._get_tiled_client()
        if isinstance(client, dict) and client.get('status') == 'error':
            return client

        # Fetch metadata for each entry
        metadata_list = []
        skipped_entries = []

        for entry_id in entry_ids_list:
            try:
                if entry_id not in client:
                    skipped_entries.append({
                        'entry_id': entry_id,
                        'reason': 'Entry not found in Tiled'
                    })
                    continue

                item = client[entry_id]
                tiled_metadata = dict(item.metadata) if hasattr(item, 'metadata') else {}

                # Extract all metadata fields
                # Check both direct metadata and nested attrs
                attrs = tiled_metadata.get('attrs', {})
                meta = tiled_metadata.get('meta', {}) or attrs.get('meta', {})

                metadata_list.append({
                    'entry_id': entry_id,
                    'sample_name': tiled_metadata.get('sample_name') or attrs.get('sample_name', ''),
                    'sample_uuid': tiled_metadata.get('sample_uuid') or attrs.get('sample_uuid', ''),
                    'task_name': tiled_metadata.get('task_name') or attrs.get('task_name', ''),
                    'driver_name': tiled_metadata.get('driver_name') or attrs.get('driver_name', ''),
                    'AL_campaign_name': tiled_metadata.get('AL_campaign_name') or attrs.get('AL_campaign_name', ''),
                    'AL_uuid': tiled_metadata.get('AL_uuid') or attrs.get('AL_uuid', ''),
                    'meta': meta
                })

            except Exception as e:
                skipped_entries.append({
                    'entry_id': entry_id,
                    'reason': f'Error fetching metadata: {str(e)}'
                })

        return {
            'status': 'success',
            'metadata': metadata_list,
            'skipped_entries': skipped_entries
        }

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

            # Convert any object-type coordinates to strings for NetCDF compatibility
            ds_copy = combined_dataset.copy()
            for coord_name in ds_copy.coords:
                coord = ds_copy.coords[coord_name]
                if coord.dtype == object:
                    # Convert objects to strings
                    ds_copy.coords[coord_name] = coord.astype(str)

            # Also convert object-type data variables
            for var_name in ds_copy.data_vars:
                var = ds_copy[var_name]
                if var.dtype == object:
                    ds_copy[var_name] = var.astype(str)

            # Write to NetCDF with netcdf4 engine for better compatibility
            ds_copy.to_netcdf(buffer, engine='netcdf4', format='NETCDF4')
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
