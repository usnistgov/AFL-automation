import os,sys,subprocess
from pathlib import Path
try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.DummyDriver import DummyDriver

server = APIServer('DummyPumpServer')
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyPump'))
# server.init_logging(['tbm@nist.gov'])
server.run_threaded(host='0.0.0.0', port=5050, debug=False)

server = APIServer('DummyOT2Server')
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyOT2'))
server.run(host='0.0.0.0', port=5051, debug=False)
