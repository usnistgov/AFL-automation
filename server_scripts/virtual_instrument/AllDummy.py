import os,sys,subprocess
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
#this needs to be the proper DummyOT2Driver It should have the simple dummy driver container plus the thing that returns the well plate availability
from AFL.automation.APIServer.DummyOT2Driver import DummyDriver as DummyOT2Driver
from AFL.automation.APIServer.DummyDriver import DummyDriver
from AFL.automation.APIServer.data.DataTiled import DataTiled

data = DataTiled('http://localhost:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/Users/pab2/.afl/json-backup')
server = APIServer('DummyLoaderServer',index_template="index.html",data = data)
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyLoader'),add_unqueued=True)
server.run_threaded(host='0.0.0.0', port=5051)


data = DataTiled('http://localhost:8000',api_key = os.environ['TILED_API_KEY'],backup_path='~/.afl/json-backup')
server = APIServer('DummyOT2Server',index_template="index.html",data = data)
server.add_standard_routes()
server.create_queue(DummyOT2Driver(name='DummyOT2'),add_unqueued=False)
server.init_logging()
server.run(host='0.0.0.0', port=5052)
