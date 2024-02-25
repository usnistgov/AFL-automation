import sys
sys.path.insert(0,r'U:\User\Users\Martin\February_2024\AFL_automation\AFL-automation')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.instrument.ISISLARMOR import ISISLARMOR
from AFL.automation.APIServer.data.DataTiled import DataTiled


server_port=5000

data = DataTiled(
        r'http://130.246.37.131:8000',
        api_key = 'NistoRoboto642',
        backup_path=r'U:\User\Users\Martin\February_2024\tiled_backup\\'
)

driver = ISISLARMOR()
driver.config['tiled_uri'] = r'http://130.246.37.131:8000'

server = APIServer('ISISLARMOR',contact='tbm@nist.gov', data=data)
server.add_standard_routes()
server.create_queue(driver)
#server.add_unqueued_routes()
server.init_logging(toaddrs=['tbm@nist.gov','pab@nist.gov'])
server.run(host='0.0.0.0', port=server_port, debug=False)