import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.OnePumpNCNR_SampleProtocol import OnePumpNCNR_SampleProtocol


protocol = OnePumpNCNRProtocol(
        load_url='localhost:5000',
        prep_url='localhost:5001',
        )
server = DeviceServer('SampleServer')
server.add_standard_routes()
server.create_queue(protocol)
server.run(host='0.0.0.0',port=5002, debug=False)

# process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)
# 
# server.run_threaded(host='0.0.0.0', port=server_port, debug=False)
# 
# process.wait()
# 
# server._stop()
# server.join()
