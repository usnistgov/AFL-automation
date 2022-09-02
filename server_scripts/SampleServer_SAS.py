import os,sys,subprocess
from pathlib import Path

try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.sample.SAS_SampleDriver import SAS_SampleDriver
from AFL.automation.sample.SAS_LoaderV2_SampleDriver import SAS_LoaderV2_SampleDriver


driver =SAS_LoaderV2_SampleDriver(
        load_url='piloader:5000',
        prep_url='piot2:5000',
        sas_url='localhost:5000',
        camera_urls = [],
        )
server = APIServer('SAS_SampleServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tyler.martin@nist.gov','peter.beaucage@nist.gov','beaucage.peter@gmail.com','tyler.biron.martin@gmail.com'])
server.run(host='0.0.0.0',port=5050, debug=False)
