import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

server_port=5000

from NistoRoboto.APIServer.APIServer import APIServer

from NistoRoboto.loading.PushPullSelectorSampleCell import PushPullSelectorSampleCell
from NistoRoboto.loading.CetoniSyringePump import CetoniSyringePump
from NistoRoboto.loading.ViciMultiposSelector import ViciMultiposSelector
from NistoRoboto.loading.CetoniMultiPosValve import CetoniMultiPosValve
from NistoRoboto.loading.Tubing import Tubing

selector = ViciMultiposSelector(
        '/dev/ttyUSB0',
        baudrate=19200,
        portlabels={
            'catch':1,
            'cell':5,
            'waste':8,
            'rinse':9,
            'air':10,
            }
        )


pump = CetoniSyringePump('single-pump',flow_delay=5) # ID for 10mL = 14.859, for 50 mL 26.43

selector2 = CetoniMultiPosValve(pump)
driver = PushPullSelectorSampleCell(pump,
                                      selector2,
                                      catch_to_sel_vol      = Tubing(1517,112).volume(),
                                      cell_to_sel_vol       = Tubing(1517,170).volume()+0.6,
                                      syringe_to_sel_vol    = Tubing(1530,49.27+10.4).volume() ,
                                      selector_internal_vol = None,
                                      calibrated_catch_to_syringe_vol = 3.4,
                                      calibrated_syringe_to_cell_vol = 3.2,
                                      load_speed=5.0,
                                     )
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