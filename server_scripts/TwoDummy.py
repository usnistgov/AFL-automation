import os,sys,subprocess
from pathlib import Path
try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.DummyProtocol import DummyProtocol

server = DeviceServer('DummyPumpServer')
server.add_standard_routes()
server.create_queue(DummyProtocol(name='DummyPump'))
server.run_threaded(host='0.0.0.0', port=5000, debug=False)

server = DeviceServer('DummyOT2Server')
server.add_standard_routes()
server.create_queue(DummyProtocol(name='DummyOT2'))
server.run(host='0.0.0.0', port=5001, debug=False)
