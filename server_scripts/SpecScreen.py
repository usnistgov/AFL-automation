import os
from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.SpecScreenProtocol import SpecScreenProtocol

protocol = SpecScreenProtocol(log_file='/mnt/home/chess_id3b/currentdaq/beaucage-1021-1/beaucage-1021-1.tlog')
server = DeviceServer('SpecScreenServer')
server.add_standard_routes()
server.create_queue(protocol)
server.run(host='0.0.0.0', debug=False)
