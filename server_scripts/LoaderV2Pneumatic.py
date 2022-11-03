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
from AFL.automation.loading.DigitalOutPressureController import DigitalOutPressureController
from AFL.automation.loading.LabJackDigitalOut import LabJackDigitalOut
from AFL.automation.loading.LabJackSensor import LabJackSensor
from AFL.automation.loading.LoadStopperDriver import LoadStopperDriver


#load stopper stuff
sensor = LabJackSensor()
load_stopper = LoadStopperDriver(sensor,auto_initialize=False)

relayboard = PiPlatesRelay(
        {
        6:'arm-up',7:'arm-down',
        5:'rinse1',4:'rinse2',3:'blow',2:'piston-vent',1:'postsample'

        } )

digout = LabJackDigitalOut(intermittent_device_handle=False,shared_device = sensor)
p_ctrl = DigitalOutPressureController(digout,3)
pump = PressureControllerAsPump(p_ctrl,dispense_pressure = 3,implied_flow_rate = 10)
#DummyPump() # ID for 10mL = 14.859, for 50 mL 26.43
# pump = NE1kSyringePump('/dev/ttyUSB0',14.86,10,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43
# this is the line used in AFL ops   pump = NE1kSyringePump('/dev/ttyUSB0',14.6,10,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43 (gastight)
# pump = NE1kSyringePump('/dev/ttyUSB0',14.0,10,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43
# pump = NE1kSyringePump('/dev/ttyUSB0',11.4,5,baud=19200,pumpid=10,flow_delay=0) # ID for 10mL = 14.859, for 50 mL 26.43
#gpio = PiGPIO({23:'ARM_UP',24:'ARM_DOWN'},pull_dir='DOWN')
#16,19 also shot

gpio = PiGPIO({4:'DOOR',14:'ARM_UP',15:'ARM_DOWN'},pull_dir='UP') #: p21-blue, p20-purple: 1, p26-grey: 1}


driver = PneumaticSampleCell(pump,relayboard,digitalin=gpio,load_stopper=load_stopper)
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
