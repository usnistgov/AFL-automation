import os,sys,subprocess
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.driver.DummyDriver import DummyDriver
from AFL.automation.APIServer.driver.NICE_SampleDriver import NICE_SampleDriver

server = APIServer('DummyPumpServer',index_template="index_pump.html")
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyPump'))
server.init_logging()
server.run(host='0.0.0.0', port=5051)#, debug=True)
