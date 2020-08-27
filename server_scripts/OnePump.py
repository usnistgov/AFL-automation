import os,sys,subprocess

try:
	import NistoRoboto
except:
	sys.path.append('../')

server_port=5000

from NistoRoboto.DeviceServer.DeviceServer import DeviceServer

from NistoRoboto.loading.PushPullSelectorSampleCell import PushPullSelectorSampleCell
from NistoRoboto.loading.NE1kSyringePump import NE1kSyringePump
from NistoRoboto.loading.ViciMultiposSelector import ViciMultiposSelector

selector = ViciMultiposSelector('/dev/ttyFlwSel0',baudrate=19200,portlabels={'catch':5,'rinse':7,'waste':6,'air':9,'cell':8})
pump = NE1kSyringePump('/dev/ttySyrPmp0',14.86,10,baud=19200,pumpid=10) # ID for 10mL = 14.859, for 50 mL 26.43
cell = PushPullSelectorSampleCell(pump,selector)

server = DeviceServer('SampleCellServer1')
protocol = cell
server.add_standard_routes()
server.create_queue(protocol)
server.run(host='0.0.0.0',port=server_port, debug=False)

process = subprocess.Popen(f'chromium-browser --start-fullscreen http://localhost:{server_port}', shell=True, stdout=subprocess.PIPE)
process.wait()

server.stop()
server.join()