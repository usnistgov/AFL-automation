"""
ToDo
- Add support for reading h5 data written by nicos
    - get list of files, load data by file name or data title
- Add support for aborting a running command
"""
import datetime
import time

import numpy as np
import copy

from nicos.clients.base import ConnectionData, NicosClient
from nicos.utils.loggers import ACTION, INPUT
from nicos.protocols.daemon import BREAK_AFTER_LINE, BREAK_AFTER_STEP, \
     STATUS_IDLE, STATUS_IDLEEXC

#NICOS events to exclude from client
EVENTMASK = ('watch', 'datapoint', 'datacurve', 'clientexec')

MAX_MESSAGE_QUEUE_SIZE = 100000

class NicosScriptClient(NicosClient):
    """
    A client for interacting with a NICOS server from python scripts or the command line.

    Attributes
    ----------
    livedata : dict
        Dictionary to store live data from the NICOS server. This will only show data generated **after** the client has
        connected.
    status : str
        Current status of the client, either 'idle' or 'run'.
    message_queue : list
        Queue to store log messages.
    """

    livedata = {}
    status = 'idle'

    def __init__(self):
        """
        Initialize the NicosScriptClient.
        """
        NicosClient.__init__(self, self.log)
        self.message_queue = []

    def signal(self, name, data=None, exc=None):
        """
        Handle signals from the NICOS server.

        Parameters
        ----------
        name : str
            The name of the signal.
        data : any, optional
            The data associated with the signal.
        exc : any, optional
            Additional data for the signal.
        """
        accept = ['message', 'processing', 'done']
        if name in accept:
            self.log_func(name, data)
        elif name == 'livedata':
            converted_data = []
            for desc, ardata in zip(data['datadescs'], exc):
                npdata = np.frombuffer(ardata, dtype=desc['dtype'])
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
                pass

    def log(self, name, txt):
        """
        Log a message.

        Parameters
        ----------
        name : str
            The name of the log entry.
        txt : str
            The log message.
        """
        self.message_queue.append((name, txt))
        self.message_queue = self.message_queue[-MAX_MESSAGE_QUEUE_SIZE:]

    def print_queue(self):
        """
        Print and clear the message queue.
        """
        for msg in self.message_queue:
            print(f'{msg[0]}: {msg[1]}')
        self.message_queue = []

    def clear_queue(self):
        """
        Clear the message queue.
        """
        self.message_queue = []

    def connect(self, host, port, user, password):
        """
        Connect to a NICOS server.

        Parameters
        ----------
        host : str
            The hostname or IP address of the NICOS server.
        port : int
            The port number of the NICOS server.
        user : str
            The username for authentication.
        password : str
            The password for authentication.

        Raises
        ------
        RuntimeError
            If the NICOS server protocol version is incompatible.
        """
        con = ConnectionData(host, port, user, password)

        NicosClient.connect(self, con, EVENTMASK)
        if self.daemon_info.get('protocol_version') < 22:
            raise RuntimeError("incompatible nicos server")

        state = self.ask('getstatus')
        self.signal('status', state['status'])
        self.print_queue()
        if self.isconnected:
            print('Successfully connected to %s' % host)
        else:
            print('Failed to connect to %s' % host)

    def command(self, line, interactive=False):
        """
        Send a command to the NICOS server.

        Parameters
        ----------
        line : str
            The command to send.
        interactive : bool, optional
            Whether to run the command interactively.

        Returns
        -------
        any
            The result of the command.
        """
        com = "%s" % line.strip()
        if interactive:
            return self._interactive(com)
        else:
            return self.run(com)

    def _interactive(self, com):
        """
        Run a command interactively.

        Parameters
        ----------
        com : str
            The command to run.

        Returns
        -------
        any
            The result of the command.
        """
        start_detected = False
        ignore = [ACTION, INPUT]
        reqID = None

        if self.status == 'idle':
            self.run(com)
        else:
            return 'NICOS is busy, cannot send commands'

        while True:
            if self.message_queue:
                work_queue = copy.deepcopy(self.message_queue)
                self.message_queue = []
                for name, message in work_queue:
                    if name == 'processing':
                        if message['script'] == com:
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
        Get the value of a parameter.

        Parameters
        ----------
        parameter : str
            The name of the parameter.

        Returns
        -------
        any
            The value of the parameter.
        """
        if parameter in self.livedata:
            return self.livedata[parameter]

        if parameter == 'scandata':
            xs, ys, _, names = self.eval(
                '__import__("nicos").commands.analyze._getData()[:4]')
            return xs, ys, names

        if parameter.find('.') > 0:
            devpar = parameter.split('.')
            return self.getDeviceParam(devpar[0], devpar[1])
        else:
            return self.getDeviceValue(parameter)
    def blockForIdle(self, timeout=1800, initial_delay=5):
        """
        Block execution until the client status is 'idle' or a timeout occurs.

        Parameters
        ----------
        timeout : int, optional
            The maximum time to wait in seconds (default is 1800 seconds).
        initial_delay : int, optional
            The initial delay before starting to check the status in seconds (default is 5 seconds).

        Notes
        -----
        This method will block the execution of the script until the client's status becomes 'idle' or the specified timeout is reached.
        It checks the status every 0.1 seconds after the initial delay.
        """
        time.sleep(initial_delay)

        start_time = datetime.datetime.now()
        end_time = start_time + datetime.timedelta(seconds=timeout)

        while datetime.datetime.now() < end_time:
            if self.status == 'idle':
                return
            time.sleep(0.1)

        raise TimeoutError(f"Timeout of {timeout} seconds reached while waiting for idle status")
    def stop_after_step(self):
        """
        Stop the client after the current step.
        """
        self.tell('stop', BREAK_AFTER_STEP)

    def estop(self):
        """
        Emergency stop the client.
        """
        self.tell('emergency')
    def stop(self, after_command=True, after_scan_point=False, emergency=False):
        """
        Stop the client based on the specified conditions.

        Parameters
        ----------
        after_command : bool, optional
            If True, stop the client after the current command (default is True).
        after_scan_point : bool, optional
            If True, stop the client after the current scan point (default is False).
        emergency : bool, optional
            If True, perform an emergency stop (default is False).

        Notes
        -----
        This method allows stopping the client in different ways:
        - If `emergency` is True, an emergency stop is performed.
        - If `after_command` is True, the client stops after the current command.
        - If `after_scan_point` is True, the client stops after the current scan point.
        """
        if emergency:
            self.estop()
        elif after_command:
            self.tell('stop', BREAK_AFTER_LINE)
        elif after_scan_point:
            self.tell('stop', BREAK_AFTER_STEP)
