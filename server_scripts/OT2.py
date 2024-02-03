from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.prepare.OT2_Driver import OT2_Driver
from AFL.automation.APIServer.data.DataTiled import DataTiled


import os
#data = DataTiled('http://10.42.0.1:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/root/.afl/json-backup')
#server = APIServer('OT2Server',data = data)
server = APIServer('OT2Server')
driver = OT2_Driver()
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tbm@nist.gov'])
server.run(host='0.0.0.0', debug=False)
