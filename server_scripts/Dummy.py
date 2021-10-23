import os,sys,subprocess
from pathlib import Path
try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.driver.DummyDriver import DummyDriver
from NistoRoboto.APIServer.driver.NICE_SampleDriver import NICE_SampleDriver

server = APIServer('DummyPumpServer',index_template="index_pump.html")
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyPump'))

server.task_queue.put({'task':{'task_name':'dummy1'},'meta':{},'uuid':'1234-5678-91011'})
server.task_queue.put({'task':{'task_name':'dummy2'},'meta':{},'uuid':'1234-5678-91012'})
server.task_queue.put({'task':{'task_name':'dummy3'},'meta':{},'uuid':'1234-5678-91013'})
server.queue_daemon.paused = True

server.init_logging()
server.run(host='0.0.0.0', port=5051)#, debug=True)

