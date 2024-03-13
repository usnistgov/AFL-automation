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

AFL_GLOBAL_CONFIG = PersistentConfig(
        os.path.join(os.path.expanduser('~'),'.afl','config.json'),
        defaults = {
        'owner_email': '',
        'system_serial': 'Default',
        'tiled_server' : '',
        'tiled_api_key': '',
        'bind_address': '0.0.0.0',
        'ports': {},
        },
        max_history=100,
)

try:
    main_module = _override_main_module_
except NameError:
    import __main__
    main_module_fullpath = os.path.abspath(__main__.__file__)
    main_module_name = os.path.basename(main_module_fullpath).replace('.py','')
driver_module = importlib.import_module(main_module_name,'')
driver_cls = getattr(driver_module,driver_module.__name__.split('.')[-1])

if 'AFL_SYSTEM_SERIAL' not in os.environ.keys():
        os.environ['AFL_SYSTEM_SERIAL'] = AFL_GLOBAL_CONFIG['system_serial']

if main_module_name in AFL_GLOBAL_CONFIG['ports'].keys():
        server_port = AFL_GLOBAL_CONFIG['ports'][main_module_name]
else:
        server_port=5000

driver = driver_cls()
if len(AFL_GLOBAL_CONFIG['tiled_server'])>0:
        data = DataTiled(AFL_GLOBAL_CONFIG['tiled_server'],
                api_key = AFL_GLOBAL_CONFIG['tiled_api_key'],
                backup_path= os.path.join(os.path.expanduser('~'),'.afl','json-backup'),)
else:
        data = None
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
