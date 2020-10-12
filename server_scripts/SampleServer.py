import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.driver.NICE_SampleDriver import NICE_SampleDriver


driver =NICE_SampleDriver(
        nice_url='NGBSANS.ncnr.nist.gov',
        load_url='piloader:5000',
        prep_url='piot2:5000',
        camera_urls = [
            # 'http://picam:8081/1/current',
            'http://picam:8081/2/current',
            'http://picam:8081/3/current',
            ]
        )
server = APIServer('SampleServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tyler.martin@nist.gov'])
server.run(host='0.0.0.0',port=5000, debug=False)
