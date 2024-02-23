import os,sys,subprocess
from pathlib import Path

try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.driver.NICE_SampleDriver import NICE_SampleDriver
from AFL.automation.APIServer.driver.SampleDriver import SampleDriver


# driver =NICE_SampleDriver(
#         nice_url='NGBSANS.ncnr.nist.gov',
#         load_url='piloader2:5000',
#         prep_url='piot2:5000',
#         camera_urls = [
#             'http://robocam:8081/101/current',
#             'http://robocam:8081/102/current',
#             ]
#         )
driver =SampleDriver(
        load_url='piloader2:5000',
        prep_url='piot2:5000',
        camera_urls = [
            'http://robocam:8081/102/current',
            'http://robocam:8081/105/current',
            ]
        )
server = APIServer('SampleServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tyler.martin@nist.gov','peter.beaucage@nist.gov','beaucage.peter@gmail.com'])
server.run(host='0.0.0.0',port=5000, debug=False)
