import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

server_port=5000

from NistoRoboto.APIServer.APIServer import APIServer

from NistoRoboto.loading.TwoSelectorBlowoutSampleCell import TwoSelectorBlowoutSampleCell
from NistoRoboto.loading.NE1kSyringePump import NE1kSyringePump
from NistoRoboto.loading.ViciMultiposSelector import ViciMultiposSelector

# selector = ViciMultiposSelector(
#         '/dev/ttyFlowSel',
#         baudrate=19200,
#         portlabels={
#             'catch':1,
#             'cell':2,
#             'cell2':3,
#             'waste':4,
#             'rinse':5,
#             'air':10,
#             }
#         )
# selector = ViciMultiposSelector(
#         '/dev/ttyFlowSel',
#         baudrate=19200,
#         portlabels={
#             'cell2':1,
#             'cell':2,
#             'catch':3,
#             'waste':4,
#             'rinse':5,
#             'air':6,
#             }
#         )
selector = ViciMultiposSelector(
        '/dev/ttyFlowSel',
        baudrate=19200,
        portlabels={
            'tefzel_cell':1,
            'cell':2,
            'catch':3,
            'waste':4,
            'rinse':5,
            'air':6,
            }
        )

blowSelector = ViciMultiposSelector(
        '/dev/ttyFlowSelBlow',
        baudrate=19200,
        portlabels={
            'pump':1,
            'blow':2,
            }
        )

pump = NE1kSyringePump('/dev/ttySyrPump',15.00,10,baud=19200,pumpid=10,flow_delay=10) # ID for 10mL = 14.859, for 50 mL 26.43

driver = TwoSelectorBlowoutSampleCell(pump, selector,blowSelector)
server = APIServer('CellServer1')
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
