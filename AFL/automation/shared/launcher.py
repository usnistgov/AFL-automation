import os,sys,subprocess,importlib,copy,json,inspect
import argparse
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find AFL.automation on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.data.DataTiled import DataTiled

from AFL.automation.shared.PersistentConfig import PersistentConfig

try:
    main_module_name = _OVERRIDE_MAIN_MODULE_NAME
except NameError:
    import __main__
    main_module_fullpath = os.path.abspath(__main__.__file__)
    main_module_name = os.path.basename(main_module_fullpath).replace('.py','')
try:
    driver_module = importlib.import_module(main_module_name,'')
except ModuleNotFoundError:
    # driver_module = sys.modules[__name__]
    driver_module = __main__
driver_name = driver_module.__name__.split('.')[-1]
try:
    main_module_name = driver_module._OVERRIDE_MAIN_MODULE_NAME
    print(f'found override {main_module_name}')
except AttributeError:
    pass
driver_cls = getattr(driver_module,main_module_name)


AFL_GLOBAL_CONFIG = PersistentConfig(
        os.path.join(os.path.expanduser('~'),'.afl','config.json'),
        defaults = {
        'owner_email': '',
        'system_serial': 'Default',
        'tiled_server' : '',
        'tiled_api_key': '',
        'bind_address': '0.0.0.0',
        'ports': {},
        'driver_custom_configs': {},
        'ca_status_enabled': False,
        'ca_status_ports': {}
        },
        max_history=100,
)
print(AFL_GLOBAL_CONFIG['ca_status_enabled'])
try:
        _DEFAULT_PORT = driver_module._DEFAULT_PORT
        # if this driver has not provided a default custom config, we simply throw a NameError
        # and move on
        if main_module_name not in AFL_GLOBAL_CONFIG['ports'].keys():
                # if there is already global config for this driver, do nothing, otherwise...
                dports = AFL_GLOBAL_CONFIG['ports']
                dports[main_module_name]  = _DEFAULT_PORT
                AFL_GLOBAL_CONFIG['ports'] = dports              
                print(f'added previously missing custom port for {main_module_name} to local file')
except (AttributeError,NameError):
        pass
if 'AFL_SYSTEM_SERIAL' not in os.environ.keys():
        os.environ['AFL_SYSTEM_SERIAL'] = AFL_GLOBAL_CONFIG['system_serial']

if main_module_name in AFL_GLOBAL_CONFIG['ports'].keys():
        server_port = AFL_GLOBAL_CONFIG['ports'][main_module_name]
        print(f'Found configured non-default port {server_port}, starting there')
else:
        server_port=5000

if main_module_name in AFL_GLOBAL_CONFIG.get('ca_status_ports', {}):
        ca_status_port = AFL_GLOBAL_CONFIG['ca_status_ports'][main_module_name]
else:
        ca_status_port = 5064

if len(AFL_GLOBAL_CONFIG['tiled_server'])>0:
        tiled_server = AFL_GLOBAL_CONFIG['tiled_server']
        try:
                data = DataTiled(tiled_server,
                        api_key = AFL_GLOBAL_CONFIG['tiled_api_key'],
                        backup_path= os.path.join(os.path.expanduser('~'),'.afl','json-backup'),)
        except Exception as exc:
                print(
                        f'Warning: unable to connect to configured Tiled server {tiled_server!r}: {exc}. '
                        'Continuing without a Tiled data backend.',
                        file=sys.stderr,
                )
                data = None
else:
        data = None

def _reconstitute_objects(obj_dict,data=None):
        if not isinstance(obj_dict,dict):
            if isinstance(obj_dict,list):
                rlist = []
                for itm in obj_dict:
                    rlist.append(_reconstitute_objects(itm,data=data))
                return rlist
            else:
                return obj_dict
        if '_classname' not in obj_dict.keys():
                return obj_dict
        # Reconstruction consumes _classname/_args below. Work on a copy so a
        # debounced PersistentConfig write cannot save a stripped driver
        # configuration and make the next launch receive a plain dict.
        obj_dict = copy.deepcopy(obj_dict)
        class_to_make = obj_dict.pop('_classname')
        if '_args' in obj_dict.keys():
                _args = obj_dict.pop('_args')
        else:
                _args = []
        args = []
        for item in _args:
                args.append(_reconstitute_objects(item,data=data))

        kwargs = {}
        if '_add_data' in obj_dict.keys():
               data_name = obj_dict.pop('_add_data')
               kwargs[data_name] = data
        for k,v in obj_dict.items():
                kwargs[k] = _reconstitute_objects(v,data=data)
        class_module_name = '.'.join(class_to_make.split('.')[:-1])
        class_module = importlib.import_module(class_module_name,'')
        cls_name = class_to_make.split('.')[-1]
        cls_obj = getattr(class_module, cls_name)
        return cls_obj(*args,**kwargs)

'''
        example input for driver_custom_configs:

        'PneumaticPressureLoader':
                '_classname': 'AFL.automation.loading.PneumaticPressureLoader.PneumaticPressureLoader',
                'p_ctrl': { '_classname': 'AFL.automation.loading.DigitalOutPressureController.DigitalOutPressureController',
                            'dig_out': {
                                 '_classname': 'AFL.automation.loading.LabJackDigitalOut',
                                 'port': 'DIO1'}}}


'''


parser = argparse.ArgumentParser(prog = f'AFL // {main_module_name}',
                                description = f'AFL APIServer launcher for {main_module_name}')
parser.add_argument('--no-waitress', action='store_true',
                    help='Disable the waitress WSGI server')
parser.add_argument('--config', type=Path, metavar='CONFIG.json',
                    help='Launch using this JSON driver configuration instead of defaults')

parser.add_argument('-i', '--interactive', action='store_true',
                    help='Start in interactive mode')
args = parser.parse_args()

# Driver construction must not inherit values from an earlier run.  This is
# consumed by Driver and applies to every Driver created by a custom config.
os.environ['AFL_FRESH_DRIVER_CONFIG'] = '1'

def _read_launch_config(config_path):
        try:
                with config_path.open() as config_file:
                        config = json.load(config_file)
        except (OSError, json.JSONDecodeError) as exc:
                parser.error(f'Unable to read --config file {config_path}: {exc}')
        if not isinstance(config, dict):
                parser.error('--config must contain a JSON object')
        return config

def _config_root():
        configured_home = os.environ.get('AFL_HOME')
        if configured_home is None or not configured_home.strip():
                configured_home = Path.home() / '.afl'
        return Path(configured_home).expanduser() / 'configs'

def _write_bootstrap_config(driver_name, config):
        """Write launch defaults before hardware-dependent construction."""
        config_path = _config_root() / f'{driver_name}.config.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = config_path.with_suffix(config_path.suffix + '.tmp')
        try:
                with temporary_path.open('w') as config_file:
                        json.dump(config, config_file, indent=4)
                temporary_path.replace(config_path)
        except Exception:
                if temporary_path.exists():
                        temporary_path.unlink()
                raise
        return config_path

launch_config = _read_launch_config(args.config) if args.config is not None else None
default_custom_config = getattr(driver_module, '_DEFAULT_CUSTOM_CONFIG', None)
is_custom_config = isinstance(launch_config, dict) and '_classname' in launch_config
uses_default_custom_config = launch_config is None and isinstance(default_custom_config, dict) and '_classname' in default_custom_config

if is_custom_config:
        bootstrap_driver_name = launch_config['_classname'].rsplit('.', 1)[-1]
        bootstrap_config = copy.deepcopy(launch_config.get('overrides', {}))
elif uses_default_custom_config:
        bootstrap_driver_name = default_custom_config['_classname'].rsplit('.', 1)[-1]
        bootstrap_config = copy.deepcopy(default_custom_config.get('overrides', {}))
else:
        bootstrap_driver_name = driver_cls.__name__
        bootstrap_config = copy.deepcopy(driver_cls.gather_defaults())
        if launch_config is not None:
                bootstrap_config.update(launch_config)

# This plain JSON file is available even if creating the driver fails while
# connecting to hardware.  Users can edit it and pass it back with --config.
_write_bootstrap_config(bootstrap_driver_name, bootstrap_config)

if is_custom_config:
                print(f'launching from custom config {args.config}')
                driver = _reconstitute_objects(launch_config,data=data)
elif uses_default_custom_config:
        print(f'launching from declared default config for {main_module_name}')
        driver = _reconstitute_objects(default_custom_config,data=data)
elif 'overrides' in inspect.signature(driver_cls).parameters:
        driver = driver_cls(overrides=bootstrap_config)
else:
        driver = driver_cls()
        if launch_config is not None:
                driver.set_config(**launch_config)

# The driver name can differ from its class name.  Refresh the pre-launch
# snapshot with the resolved configuration before server setup begins.
latest_config_path = driver.path / 'configs' / f'{driver.name}.config.json'
driver.config.write_current_config(latest_config_path)

server = APIServer(main_module_name,data=data,contact=AFL_GLOBAL_CONFIG['owner_email'])
server.add_standard_routes()

# optionally publish queue status over CA
start_ca = AFL_GLOBAL_CONFIG.get('ca_status_enabled', False)
server.create_queue(
        driver,
        start_ca=start_ca,
        ca_prefix=f"AFL:{AFL_GLOBAL_CONFIG['system_serial']}:{main_module_name}:",
        ca_port=ca_status_port,
)

#server.add_unqueued_routes()
# APIServer initializes logging in its constructor.

#process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)
if args.interactive:
        server.run_threaded(host=AFL_GLOBAL_CONFIG['bind_address'],
                            port=server_port,
                            use_waitress=None if not args.no_waitress else False)
        import code,time
        time.sleep(1) # this is mostly cosmetic, to let the server spin up.
        code.interact(local=globals(), banner = 'AFL APIServer started.  Access driver in "driver" global object, APIServer in "server".  Exit with ctrl-D or exit().  Have a lot of fun...')

else:
        server.run(host=AFL_GLOBAL_CONFIG['bind_address'],
                   port=server_port,
                   use_waitress=None if not args.no_waitress else False)

#process.wait()

#server._stop()
#server.join()
