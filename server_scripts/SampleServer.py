import os,sys,subprocess
from pathlib import Path

try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.sample.SampleDriver import SampleDriver
from AFL.automation.APIServer.data.DataTiled import DataTiled

tiled_uri = 'http://10.42.0.1:8000'
data = DataTiled(server=tiled_uri, api_key = os.environ['TILED_API_KEY'],backup_path='/home/afl642/.afl/json-backup')

driver =SampleDriver(
        tiled_uri = tiled_uri,
        camera_urls = [ ],
        snapshot_directory= '/home/afl642/snaps'
        )
server = APIServer('SampleServerTest',data=data)
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=[])
server.run(host='0.0.0.0',port=5000, debug=False)
