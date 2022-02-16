import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.driver.SAS_SampleDriver import SAS_SampleDriver


driver =SAS_SampleDriver(
        load_url='piloader:5000',
        prep_url='piot2:5000',
        sas_url='lnx-id3b-1.classe.cornell.edu:5000',
        camera_urls = [
            'http://robocam:8081/3/current',
            'http://robocam:8081/5/current',
            'http://robocam:8081/6/current',
            'http://robocam:8081/8/current',
            ]
        )
server = APIServer('SAS_SampleServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tyler.martin@nist.gov','peter.beaucage@nist.gov','beaucage.peter@gmail.com','tyler.biron.martin@gmail.com'])
server.run(host='0.0.0.0',port=5000, debug=False)
