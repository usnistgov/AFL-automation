import os,sys,subprocess
from pathlib import Path
try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.APIServer.APIServer import APIServer
from NistoRoboto.agent.SAS_AgentDriver import SAS_AgentDriver
from NistoRoboto.agent.SAS_AL_SampleDriver import SAS_AL_SampleDriver

server = APIServer('SAS_Agent',index_template="index.html")
server.add_standard_routes()
server.create_queue(SAS_AgentDriver())
server.init_logging()
server.run_threaded(host='0.0.0.0', port=5050)#, debug=True)

driver =SAS_AL_SampleDriver(
        load_url='piloader:5000',
        prep_url='piot2:5000',
        sas_url='lnx-id3b-1.classe.cornell.edu:5000',
        agent_url='localhost:5050',
        camera_urls = [],
        dummy_mode=True,
        )

server = APIServer('SAS_AL_SampleDriver',index_template="index.html")
server.add_standard_routes()
server.create_queue(driver)
server.init_logging()
server.run(host='0.0.0.0', port=5051)#, debug=True)
