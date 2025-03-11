import os,sys,subprocess
from pathlib import Path

try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

server_port=5000

from AFL.automation.APIServer.APIServer import APIServer

from AFL.automation.loading.PneumaticSampleCell import PneumaticSampleCell
from AFL.automation.loading.DummyPump import DummyPump
from AFL.automation.loading.SainSmartRelay import SainSmartRelay
from AFL.automation.loading.Tubing import Tubing

relayboard = SainSmartRelay(
        {
        1:'arm-up',2:'arm-down',
                3:'rinse1',4:'rinse2',5:'blow',6:'enable',7:'piston-vent',8:'postsample'

        },
        '/dev/tty.usbserial-14440'
        )
pump = DummyPump() # ID for 10mL = 14.859, for 50 mL 26.43
driver = PneumaticSampleCell(pump,relayboard)
server = APIServer('CellServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tbm@nist.gov'])
server.run(host='0.0.0.0',port=server_port, debug=False)


# process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)
# 
# server.run_threaded(host='0.0.0.0', port=server_port, debug=False)
# 
# process.wait()
# 
# server._stop()
# server.join()
