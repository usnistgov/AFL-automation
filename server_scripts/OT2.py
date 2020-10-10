from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.OT2Protocol import OT2Protocol

server = DeviceServer('OT2Server')
protocol = OT2Protocol()
server.add_standard_routes()
server.create_queue(protocol)
server.init_logging(toaddrs=['tbm@nist.gov'])
server.run(host='0.0.0.0', debug=False)
