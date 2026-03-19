from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared import serialization
import logging
import inspect
import pathlib
import uuid
import os

from AFL.automation.APIServer.DriverWebAppsMixin import DriverWebAppsMixin

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


class Driver(DriverWebAppsMixin):
    unqueued = makeRegistrar()
    queued = makeRegistrar()
    quickbar = makeRegistrar()
    # Mapping of url subpaths to filesystem directories containing static assets
    # Example: {'docs': '/path/to/docs', 'assets': pathlib.Path(__file__).parent / 'assets'}
    # Files will be served at /static/{subpath}/{filename}
    static_dirs = {}

    def __init__(self, name, defaults=None, overrides=None, useful_links=None, afl_home=None):
        self.app = None
        self.data = None
        self.dropbox = None
        self.logger = logging.getLogger(name if name is not None else 'Driver')
        self.logger.setLevel(logging.INFO)
        self._tiled_client = None  # Cached Tiled client
        self._combined_dataset_cache = {}
        self._combined_dataset_cache_order = []
        self._max_combined_dataset_cache = 3

        if name is None:
            self.name = 'Driver'
        else:
            self.name = name

        if useful_links is None:
            self.useful_links = {"Tiled Browser": "/tiled_browser"}
        else:
            useful_links["Tiled Browser"] = "/tiled_browser"
            self.useful_links = useful_links

        resolved_afl_home = afl_home if afl_home is not None else os.environ.get('AFL_HOME')
        if resolved_afl_home is None or str(resolved_afl_home).strip() == '':
            resolved_afl_home = pathlib.Path.home() / '.afl'
        self.path = pathlib.Path(resolved_afl_home).expanduser()
        self.path.mkdir(exist_ok=True,parents=True)
        self.filepath = self.path / (name + '.config.json')

        self.config = PersistentConfig(
            path=self.filepath,
            defaults= defaults,
            overrides= overrides,
            )
        
        # collect inherited static directories
        self.static_dirs = self.gather_static_dirs()

    def _log(self, level, message):
        if self.app is not None and hasattr(self.app, 'logger'):
            log_func = getattr(self.app.logger, level, None)
            if log_func:
                log_func(message)
        else:
            log_func = getattr(self.logger, level, None)
            if log_func:
                log_func(message)

    def log_info(self, message):
        self._log('info', message)

    def log_error(self, message):
        self._log('error', message)

    def log_debug(self, message):
        self._log('debug', message)

    def log_warning(self, message):
        self._log('warning', message)


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
            self.log_info(f'{name:30s} = {value}')

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
                self.log_info(f'{name:30s} = {value}')
        return config.config

    def clean_config(self):
        """Remove any config keys that are not present in defaults.

        This method gathers all defaults from the class hierarchy, makes a copy
        of the current config, and removes any keys that don't exist in the defaults.
        The cleaned config is then saved back to the persistent config.

        Returns
        -------
        dict
            Dictionary containing the keys that were removed from config
        """
        import copy

        # Get all valid default keys from class hierarchy
        defaults = self.gather_defaults()

        # Make a copy of current config
        current_config = copy.deepcopy(self.config.config)

        # Find keys that are not in defaults
        removed_keys = {}
        for key in list(current_config.keys()):
            if key not in defaults:
                removed_keys[key] = current_config[key]
                del current_config[key]

        # Update config with cleaned version
        if removed_keys:
            # Clear and rebuild config with only valid keys
            self.config.config = current_config
            self.config.save()

        return removed_keys

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
        self.app.logger.info(f'Storing object in dropbox as {uid}')
        self.dropbox[uid] = obj
        return uid

    @unqueued(render_hint='html')
    def tiled_browser(self, **kwargs):
        """Serve the Tiled database browser HTML interface."""
        return super().tiled_browser(**kwargs)

    @unqueued(render_hint='html')
    def tiled_plot(self, **kwargs):
        """Serve the Tiled plotting interface for selected entries."""
        return super().tiled_plot(**kwargs)

    @unqueued(render_hint='html')
    def tiled_gantt(self, **kwargs):
        """Serve the Tiled Gantt chart interface for selected entries."""
        return super().tiled_gantt(**kwargs)

    @unqueued()
    def tiled_config(self, **kwargs):
        """Return Tiled server configuration from shared config file."""
        return super().tiled_config(**kwargs)

    @unqueued()
    def tiled_search(self, queries='', filters='', sort='', fields='', offset=0, limit=50, **kwargs):
        """Proxy endpoint for Tiled metadata search to avoid CORS issues."""
        return super().tiled_search(
            queries=queries,
            filters=filters,
            sort=sort,
            fields=fields,
            offset=offset,
            limit=limit,
            **kwargs,
        )

    @unqueued()
    def tiled_get_data(self, entry_id, **kwargs):
        """Proxy endpoint to get xarray HTML representation from Tiled."""
        return super().tiled_get_data(entry_id, **kwargs)

    @unqueued()
    def tiled_get_xarray_html(self, entry_ids, **kwargs):
        """Return xarray _repr_html_() for one or more Tiled entries."""
        return super().tiled_get_xarray_html(entry_ids, **kwargs)

    @unqueued()
    def tiled_get_plot_manifest(self, entry_ids, **kwargs):
        """Return plot-manifest metadata for one or more Tiled entries."""
        return super().tiled_get_plot_manifest(entry_ids, **kwargs)

    @unqueued()
    def tiled_get_plot_variable(self, entry_ids, var_name, **kwargs):
        """Return one variable from the cached combined plot dataset."""
        return super().tiled_get_plot_variable(entry_ids, var_name, **kwargs)

    @unqueued()
    def tiled_get_metadata(self, entry_id, **kwargs):
        """Proxy endpoint to get metadata from Tiled."""
        return super().tiled_get_metadata(entry_id, **kwargs)

    @unqueued()
    def tiled_get_full_json(self, entry_id, **kwargs):
        """Proxy endpoint to get JSON-serializable full data for one entry."""
        return super().tiled_get_full_json(entry_id, **kwargs)

    @unqueued()
    def tiled_get_distinct_values(self, field, **kwargs):
        """Get distinct values for a metadata field from Tiled."""
        return super().tiled_get_distinct_values(field, **kwargs)

    @unqueued()
    def tiled_upload_dataset(
        self,
        dataset=None,
        upload_bytes=None,
        filename='',
        file_format='',
        coordinate_column='',
        metadata=None,
        delimiter='',
        comment_prefix='',
        last_comment_as_header='',
        **kwargs,
    ):
        """Upload xarray/csv/tsv/dat data into Tiled."""
        return super().tiled_upload_dataset(
            dataset=dataset,
            upload_bytes=upload_bytes,
            filename=filename,
            file_format=file_format,
            coordinate_column=coordinate_column,
            metadata=metadata,
            delimiter=delimiter,
            comment_prefix=comment_prefix,
            last_comment_as_header=last_comment_as_header,
            **kwargs,
        )
