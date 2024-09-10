# *****************************************************************************
# NICOS, the Networked Instrument Control System of the MLZ
# Copyright (c) 2009-2024 by the NICOS contributors (see AUTHORS)
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Module authors:
#   Mark Koennecke, <mark.koennecke@psi.ch>
#
# *****************************************************************************

import copy

import numpy as np

from nicos.clients.base import ConnectionData, NicosClient
from nicos.protocols.daemon import STATUS_IDLE, STATUS_IDLEEXC
from nicos.utils.loggers import ACTION, INPUT

EVENTMASK = ('watch', 'datapoint', 'datacurve',
             'clientexec')


class AFL_NicosClient(NicosClient):

    livedata = {}
    status = 'idle'

    def __init__(self):
        NicosClient.__init__(self, self.log)
        self.message_queue = []

    def signal(self, name, data=None, exc=None):
        accept = ['message', 'processing', 'done']
        if name in accept:
            self.log_func(name, data)
        elif name == 'livedata':
            converted_data = []
            for desc, ardata in zip(data['datadescs'], exc):
                npdata = np.frombuffer(ardata,
                                       dtype=desc['dtype'])
                npdata = npdata.reshape(desc['shape'])
                converted_data.append(npdata)
            self.livedata[data['det'] + '_live'] = converted_data
        elif name == 'status':
            status, _ = data
            if status == STATUS_IDLE or status == STATUS_IDLEEXC:
                self.status = 'idle'
            else:
                self.status = 'run'
        else:
            if name != 'cache':
                # print(name, data)
                pass

    def log(self, name, txt):
        self.message_queue.append((name, txt))

    def print_queue(self):
        for msg in self.message_queue:
            print(f'{msg[0]}: {msg[1]}')
        self.message_queue = []

    def connect(self, host, port, user, password):
        con = ConnectionData(host, port, user, password)

        NicosClient.connect(self, con, EVENTMASK)
        if self.daemon_info.get('protocol_version') < 22:
            raise RuntimeError("incompatible nicos server")

        state = self.ask('getstatus')
        self.signal('status', state['status'])
        self.print_queue()
        if self.isconnected:
            print('Successfully connected to %s' % url)
        else:
            print('Failed to connect to %s' % url)

    def _command(self, line):
        com = "%s" % line.strip()
        if self.status == 'idle':
            self.run(com)
            return com
        return None

    def command(self, line):
        start_detected = False
        ignore = [ACTION, INPUT]
        reqID = None
        testcom = self._command(line)
        if not testcom:
            return 'NICOS is busy, cannot send commands'
        while True:
            if self.message_queue:
                # own copy for thread safety
                work_queue = copy.deepcopy(self.message_queue)
                self.message_queue = []
                for name, message in work_queue:
                    print(f'COMMAND: NAME={name} MESSAGE={message}')
                    if name == 'processing':
                        if message['script'] == testcom:
                            start_detected = True
                            reqID = message['reqid']
                        continue
                    if name == 'done' and message['reqid'] == reqID:
                        return
                    if message[2] in ignore:
                        continue
                    if message[0] != 'nicos':
                        messagetxt = message[0] + ' ' + message[3]
                    else:
                        messagetxt = message[3]
                    if start_detected and reqID == message[-1]:
                        print(messagetxt.strip())

    def val(self, parameter):
        """
        This can be implemented on top of the client.devValue()
        and devParamValue() interfaces. The problem to be solved is
        how to make the data visible in ipython
        """
        # check for livedata first
        if parameter in self.livedata:
            return self.livedata[parameter]

        # Now check for scan data
        if parameter == 'scandata':
            xs, ys, _, names = self.eval(
                '__import__("nicos").commands.analyze._getData()[:4]')
            return xs, ys, names

        # Try get device data from NICOS
        if parameter.find('.') > 0:
            devpar = parameter.split('.')
            return self.getDeviceParam(devpar[0], devpar[1])
        else:
            return self.getDeviceValue(parameter)

    def list_livedata(self):
        print('Available livedata:')
        keys = self.livedata.keys()
        for k in keys:
            print(k)
