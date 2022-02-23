import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.driver.SAS_LoaderV2_SampleDriver import SAS_LoaderV2_SampleDriver
from NistoRoboto.instrument.DummySAS import DummySAS

server = APIServer('Dummy_SAS_Instrument')
server.add_standard_routes()
server.create_queue(DummySAS())
server.init_logging(toaddrs=['tyler.martin@nist.gov','peter.beaucage@nist.gov','beaucage.peter@gmail.com','tyler.biron.martin@gmail.com'])
server.run_threaded(host='0.0.0.0',port=5001, debug=False)


driver =SAS_LoaderV2_SampleDriver(
        load_url='piloader:5000',
        prep_url='piot2:5000',
        sas_url='localhost:5001',
        camera_urls = [ ]
        )
server = APIServer('SAS_SampleServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(toaddrs=['tyler.martin@nist.gov','peter.beaucage@nist.gov','beaucage.peter@gmail.com','tyler.biron.martin@gmail.com'])
server.run(host='0.0.0.0',port=5000, debug=False)
