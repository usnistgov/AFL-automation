from NistoRoboto.DeviceServer.DeviceServer import DeviceServer
from NistoRoboto.DeviceServer.OT2Protocol import OT2Protocol
import os
server = DeviceServer('OT2Server')
protocol = OT2Protocol()
server.add_standard_routes()
server.create_queue(protocol)

import logging
from logging.handlers import SMTPHandler
mail_handler = SMTPHandler(mailhost=('smtp.nist.gov',25),
                   fromaddr='OT2@pg93001.ncnr.nist.gov',
                   toaddrs='tbm@nist.gov', subject='Protocol Error')
mail_handler.setLevel(logging.ERROR)
server.app.logger.addHandler(mail_handler)

server.run(host='0.0.0.0', debug=False)
