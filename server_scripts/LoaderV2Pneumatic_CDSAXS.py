import os,sys,subprocess
from pathlib import Path

try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find AFL.automation on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

server_port=5000

from AFL.automation.APIServer.APIServer import APIServer

from AFL.automation.loading.PneumaticSampleCell import PneumaticSampleCell
from AFL.automation.loading.DummyPump import DummyPump
from AFL.automation.loading.NE1kSyringePump import NE1kSyringePump
from AFL.automation.loading.PiPlatesRelay import PiPlatesRelay
from AFL.automation.loading.SainSmartRelay import SainSmartRelay
from AFL.automation.loading.PiGPIO import PiGPIO
from AFL.automation.loading.Tubing import Tubing
from AFL.automation.loading.PressureControllerAsPump import PressureControllerAsPump
from AFL.automation.loading.UltimusVPressureController import UltimusVPressureController
#from AFL.automation.loading.DigitalOutPressureController import DigitalOutPressureController
from AFL.automation.loading.LabJackDigitalOut import LabJackDigitalOut
from AFL.automation.loading.LabJackSensor import LabJackSensor
from AFL.automation.loading.LoadStopperDriver import LoadStopperDriver
from AFL.automation.APIServer.data.DataTiled import DataTiled

data = DataTiled('http://afl-inst-lab.campus.nist.gov:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/home/pi/.afl/json-backup')


#load stopper stuff
sensor = LabJackSensor()
load_stopper = LoadStopperDriver(sensor,data=data,auto_initialize=False)
#load_stopper = None
#sensor = None

relayboard = PiPlatesRelay(
        {
#        6:'arm-up',7:'arm-down',
#        5:'rinse1',4:'rinse2',3:'blow',2:'piston-vent',1:'postsample'
        2:'arm-up',1:'arm-down',
        3:'rinse1',4:'rinse2',5:'blow',6:'piston-vent',7:'postsample'
        } )

#digout = LabJackDigitalOut(intermittent_device_handle=False,port_to_write='TDAC4',shared_device = sensor)
#p_ctrl = DigitalOutPressureController(digout,3)
p_ctrl = UltimusVPressureController('/dev/ttyUSB0')
pump = PressureControllerAsPump(p_ctrl,dispense_pressure = 7, implied_flow_rate = 5)
#DummyPump() # ID for 10mL = 14.859, for 50 mL 26.43
# pump = NE1kSyringePump('/dev/ttyUSB0',14.86,10,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43
# this is the line used in AFL ops   pump = NE1kSyringePump('/dev/ttyUSB0',14.6,10,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43 (gastight)
# pump = NE1kSyringePump('/dev/ttyUSB0',14.0,10,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43
# pump = NE1kSyringePump('/dev/ttyUSB0',11.4,5,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43
#gpio = PiGPIO({23:'ARM_UP',24:'ARM_DOWN'},pull_dir='DOWN')
#16,19 also shot

gpio = PiGPIO({4:'DOOR',14:'ARM_UP',15:'ARM_DOWN'},pull_dir='UP') #: p21-blue, p20-purple: 1, p26-grey: 1}


driver = PneumaticSampleCell(pump,relayboard,digitalin=gpio,load_stopper=load_stopper)
server = APIServer('CellServer',data=data)
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
