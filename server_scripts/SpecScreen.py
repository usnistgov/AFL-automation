import os,sys,subprocess
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.SpecScreen_Driver import SpecScreen_Driver

server_port=5000

driver = SpecScreen_Driver(log_file='/mnt/home/chess_id3b/currentdaq/beaucage-1021-1/beaucage-1021-1.tlog')
server = APIServer('SpecScreenServer')
server.add_standard_routes()
server.create_queue(driver)
server.init_logging(to_addrs=['tbm@nist.gov'])

process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)

server.run_threaded(host='0.0.0.0', port=server_port, debug=False)

process.wait()

server._stop()
server.join()
