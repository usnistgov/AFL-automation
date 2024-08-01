import os,sys,subprocess,importlib
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
driver_module = importlib.import_module(main_module_name,'')
driver_name = driver_module.__name__.split('.')[-1]
driver_cls = getattr(driver_module,driver_name)


AFL_GLOBAL_CONFIG = PersistentConfig(
        os.path.join(os.path.expanduser('~'),'.afl','config.json'),
        defaults = {
        'owner_email': '',
        'system_serial': 'Default',
        'tiled_server' : '',
        'tiled_api_key': '',
        'bind_address': '0.0.0.0',
        'ports': {},
        'driver_custom_configs': {}
        },
        max_history=100,
)
try:
        _DEFAULT_CUSTOM_CONFIG = driver_module._DEFAULT_CUSTOM_CONFIG
        # if this driver has not provided a default custom config, we simply throw a NameError
        # and move on
        if driver_name not in AFL_GLOBAL_CONFIG['driver_custom_configs'].keys():
                # if there is already global config for this driver, do nothing, otherwise...
                dccs = AFL_GLOBAL_CONFIG['driver_custom_configs']
                dccs[driver_name]  = _DEFAULT_CUSTOM_CONFIG
                AFL_GLOBAL_CONFIG['driver_custom_configs'] = dccs                
                print(f'added previously missing custom config for {driver_name} to local file')
except NameError:
        pass
if 'AFL_SYSTEM_SERIAL' not in os.environ.keys():
        os.environ['AFL_SYSTEM_SERIAL'] = AFL_GLOBAL_CONFIG['system_serial']

if main_module_name in AFL_GLOBAL_CONFIG['ports'].keys():
        server_port = AFL_GLOBAL_CONFIG['ports'][main_module_name]
else:
        server_port=5000

if len(AFL_GLOBAL_CONFIG['tiled_server'])>0:
        data = DataTiled(AFL_GLOBAL_CONFIG['tiled_server'],
                api_key = AFL_GLOBAL_CONFIG['tiled_api_key'],
                backup_path= os.path.join(os.path.expanduser('~'),'.afl','json-backup'),)
else:
        data = None

def _reconstitute_objects(obj_dict,data=None):
        if not isinstance(obj_dict,dict):
            if isinstance(obj_dict,list):
                rlist = []
                for itm in obj_dict:
                    rlist.append(_reconstitute_objects(itm))
                return rlist
            else:
                return obj_dict
        if '_classname' not in obj_dict.keys():
                return obj_dict
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

if main_module_name in AFL_GLOBAL_CONFIG['driver_custom_configs']:
        print(f'launching from custom config for {main_module_name}')
        driver = _reconstitute_objects(AFL_GLOBAL_CONFIG['driver_custom_configs'][main_module_name],data=data)
else:
        driver = driver_cls()
print(driver.unqueued.functions)
print(driver.unqueued.function_info)
server = APIServer(main_module_name,data=data,contact=AFL_GLOBAL_CONFIG['owner_email'])
server.add_standard_routes()

server.create_queue(driver)
#server.add_unqueued_routes()
server.init_logging(toaddrs=AFL_GLOBAL_CONFIG['owner_email'])

#process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)

server.run(host=AFL_GLOBAL_CONFIG['bind_address'], port=server_port, debug=False)#,threaded=False)

#process.wait()

#server._stop()
#server.join()
