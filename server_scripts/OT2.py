from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.OT2_Driver import OT2_Driver
import os
server = APIServer('OT2Server')
driver = OT2_Driver()
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tbm@nist.gov'])
server.run(host='0.0.0.0', debug=False)
