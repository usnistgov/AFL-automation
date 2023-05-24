import os,sys,subprocess
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.DummyDriver import DummyDriver
from AFL.automation.APIServer.data.DataTiled import DataTiled

data = DataTiled('http://afl-inst-lab.campus.nist.gov:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/Users/pab2/.afl/json-backup')
server = APIServer('DummyPumpServer',index_template="index_pump.html",data = data)
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyPump'))
server.init_logging()
server.run(host='0.0.0.0', port=5051)#, debug=True)
