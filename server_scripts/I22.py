import os,sys,subprocess
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find AFL.automation on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.instrument.I22SAXS import I22SAXS
from AFL.automation.APIServer.data.DataTiled import DataTiled

data = DataTiled('http://10.42.0.1:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/home/afl642/.afl/json-backup')
server_port=5001

driver = I22SAXS()
server = APIServer('I22SAXS',contact='pab2@nist.gov',data=data)
server.add_standard_routes()

server.create_queue(driver)
server.init_logging(toaddrs=['tbm@nist.gov','pab@nist.gov'])

server.run(host='0.0.0.0', port=server_port, debug=False)#,threaded=False)

#process.wait()

#server._stop()
#server.join()
