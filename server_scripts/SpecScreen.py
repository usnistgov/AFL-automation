import os
from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.SpecScreenProtocol import SpecScreenProtocol

SpecScreen = SpecScreenProtocol()

server = DeviceServer('SpecScreenServer')
server.add_standard_routes()
server.create_queue(SpecScreen)
server.run(host='0.0.0.0', debug=False)
