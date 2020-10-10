import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

server_port=5000

from NistoRoboto.DeviceServer.DeviceServer import DeviceServer

from NistoRoboto.loading.PushPullSelectorSampleCell import PushPullSelectorSampleCell
from NistoRoboto.loading.NE1kSyringePump import NE1kSyringePump
from NistoRoboto.loading.DoubleViciMultiposSelector import DoubleViciMultiposSelector
from NistoRoboto.loading.Tubing import Tubing

selector = DoubleViciMultiposSelector(
        '/dev/ttyFlowSel1', #connected to rinse/waste/cell/catch/etc
        '/dev/ttyFlowSel2',#conntected to pump and forced_air
        baudrate=19200,
        portlabels={
            'catch':(1,4),
            'cell':(5,4),
            'waste':(8,4),
            'rinse':(9,4),
            'air':(10,4),
            'forced_air_cell':(5,5),
            }
        )
pump = NE1kSyringePump('/dev/ttySyrPump',14.86,10,baud=19200,pumpid=10,flow_delay=10) # ID for 10mL = 14.859, for 50 mL 26.43
protocol = PushPullSelectorSampleCell(pump,
                                      selector,
                                      catch_to_sel_vol      = Tubing(1517,112).volume(),
                                      cell_to_sel_vol       = Tubing(1517,170).volume()+0.6,
                                      syringe_to_sel_vol    = Tubing(1530,49.27+10.4).volume() ,
                                      selector_internal_vol = None,
                                      calibrated_catch_to_syringe_vol = 3.4,
                                      calibrated_syringe_to_cell_vol = 3.2,
                                      load_speed=5.0,
                                     )
server = DeviceServer('CellServer')
server.add_standard_routes()
server.create_queue(protocol)
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
