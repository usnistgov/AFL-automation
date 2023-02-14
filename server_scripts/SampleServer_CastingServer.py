import os,sys,subprocess
from pathlib import Path
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.sample.CastingServer_SampleDriver import CastingServer_SampleDriver


driver = CastingServer_SampleDriver( prep_url='localhost:5000',)
server = APIServer('CastingServer_SampleServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tyler.martin@nist.gov'])
server.run(host='0.0.0.0',port=5050, debug=False)
