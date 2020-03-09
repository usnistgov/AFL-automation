import os,sys,subprocess

try:
	import NistoRoboto
except:
	sys.path.append('../')

server_port=5000

from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.SpecScreenProtocol import SpecScreenProtocol

protocol = SpecScreenProtocol(log_file='/mnt/home/chess_id3b/currentdaq/beaucage-1021-1/beaucage-1021-1.tlog')
server = DeviceServer('SpecScreenServer')
server.add_standard_routes()
server.create_queue(protocol)
server.run(host='0.0.0.0', port=server_port, debug=False)

process = subprocess.Popen(f'chromium-browser --start-fullscreen http://localhost:{server_port}', shell=True, stdout=subprocess.PIPE)
process.wait()

server.stop()
server.join()