from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.prepare.Dummy_OT2_Driver import Dummy_OT2_Driver
import os

server = APIServer('Dummy_OT2Server')
driver = Dummy_OT2_Driver()
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tbm@nist.gov'])
server.run(host='0.0.0.0', debug=False)
