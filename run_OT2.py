from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.OT2Protocol import OT2Protocol
import os
server = DeviceServer('OT2Server',
           root_path=os.getcwd()+'/NistoRoboto/DeviceServer/',
           )
protocol = OT2Protocol()
server.add_standard_routes()
server.create_queue(protocol)
server.run(host='0.0.0.0', debug=False)
