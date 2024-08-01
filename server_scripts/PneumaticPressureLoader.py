import os,sys,subprocess
from pathlib import Path

try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find AFL.automation on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

server_port=5000

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.data.DataTiled import DataTiled
# from AFL.automation.loading.PneumaticSampleCell import PneumaticSampleCell
from AFL.automation.loading.PiPlatesRelay import PiPlatesRelay
from AFL.automation.loading.PiGPIO import PiGPIO
from AFL.automation.loading.Tubing import Tubing
from AFL.automation.loading.PressureControllerAsPump import PressureControllerAsPump
from AFL.automation.loading.DigitalOutPressureController import DigitalOutPressureController
from AFL.automation.loading.LabJackDigitalOut import LabJackDigitalOut
from AFL.automation.loading.LabJackSensor import LabJackSensor
from AFL.automation.loading.LoadStopperDriver import LoadStopperDriver
from AFL.automation.loading.PneumaticPressureSampleCell import PneumaticPressureSampleCell


data = DataTiled('http://10.42.0.1:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/home/pi/.afl/json-backup')



#load stopper stuff
sensor_sans = LabJackSensor(port_to_read='AIN0',reset_port='DIO6')
load_stopper_sans = LoadStopperDriver(sensor_sans,name='LoadStopperDriver_sans',data=data,auto_initialize=False,sensorlabel='afterSANS')

sensor_spec = LabJackSensor(port_to_read='AIN1',reset_port='DIO7')
load_stopper_spec = LoadStopperDriver(sensor_spec,name='LoadStopperDriver_spec',data=data,auto_initialize=False,sensorlabel='afterSPEC')



relayboard = PiPlatesRelay(
        {
        6:'arm-up',7:'arm-down',
        5:'rinse1',4:'rinse2',3:'blow',2:'piston-vent',1:'postsample'

        } )

digout = LabJackDigitalOut(intermittent_device_handle=False,port_to_write='TDAC4',shared_device = sensor_sans)
p_ctrl = DigitalOutPressureController(digout,3)

gpio = PiGPIO({4:'DOOR',14:'ARM_UP',15:'ARM_DOWN'},pull_dir='UP') #: p21-blue, p20-purple: 1, p26-grey: 1}

driver = PneumaticPressureSampleCell(p_ctrl,relayboard,digitalin=gpio,load_stopper=[load_stopper_sans,load_stopper_spec])


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
