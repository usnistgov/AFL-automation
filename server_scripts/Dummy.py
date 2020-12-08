import os,sys,subprocess
from pathlib import Path
try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.APIServer.driver.DummyDriver import DummyDriver
from NistoRoboto.APIServer.driver.NICE_SampleDriver import NICE_SampleDriver

server = APIServer('DummyPumpServer',index_template="index_pump.html")
server.add_standard_routes()
server.create_queue(DummyDriver(name='DummyPump'))
#server.run_threaded(host='0.0.0.0', port=5051, debug=False)
server.init_logging()
server.run(host='0.0.0.0', port=5051, debug=True)

# server = APIServer('DummyOT2Server')
# server.add_standard_routes()
# server.create_queue(DummyDriver(name='DummyOT2'))
# server.run_threaded(host='0.0.0.0', port=5052, debug=False)
# 
# driver =NICE_SampleDriver(
#         nice_url=None,
#         load_url='localhost:5051',
#         prep_url='localhost:5052',
#         camera_urls = [
#             # 'http://picam:8081/1/current',
#             #'http://picam:8081/2/current',
#             #'http://picam:8081/3/current',
#             ]
#         )
# 
# server = APIServer('DummySampleServer')
# server.add_standard_routes()
# server.create_queue(driver)
# server.init_logging()
# server.run(host='0.0.0.0',port=5050, debug=False)
