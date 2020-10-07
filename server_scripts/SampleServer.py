import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.OnePumpNICE_SampleProtocol import OnePumpNICE_SampleProtocol


protocol = OnePumpNICE_SampleProtocol(
        nice_url='NGBSANS.ncnr.nist.gov',
        load_url='piloader:5000',
        prep_url='piot2:5000',
        camera_urls = [
            # 'http://picam:8081/1/current',
            'http://picam:8081/2/current',
            'http://picam:8081/3/current',
            ]
        )
server = DeviceServer('SampleServer')
server.add_standard_routes()
server.create_queue(protocol)

import logging
from logging.handlers import SMTPHandler
mail_handler = SMTPHandler(mailhost=('smtp.nist.gov',25),
                   fromaddr='SampleServer@pg93001.ncnr.nist.gov',
                   toaddrs='tbm@nist.gov', subject='Protocol Error')
mail_handler.setLevel(logging.ERROR)
server.app.logger.addHandler(mail_handler)

server.run(host='0.0.0.0',port=5000, debug=False)

# process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)
# 
# server.run_threaded(host='0.0.0.0', port=server_port, debug=False)
# 
# process.wait()
# 
# server._stop()
# server.join()
