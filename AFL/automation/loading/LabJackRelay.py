from AFL.automation.loading.MultiChannelRelay import MultiChannelRelay
import atexit
import warnings
import time
import threading
from labjack import ljm
from labjack.ljm.ljm import LJMError
import numpy as np
'''
relaylabels = {
    'EIO2': 'measurement_cell', 'EIO3': 'pressurize_bottles', 'EIO4':'catch_arm_up',
    'EIO5': 'catch_arm_down', 'EIO6': 'ambient', 'EIO7': 'rinse_bottle_1',
    'CIO1':'rinse_bottle_2'
}
ids is the inversion of this
'''

class LabJackRelay(MultiChannelRelay):

    #notes on equipment
    #high value 5V, low value 0V
    def __init__(self, relaylabels, devicetype="ANY", connection="ANY", deviceident="ANY", shared_device = None):
        '''
        Init connection to a labeled Labjack RB12 Relay module.

        Params:
        relaylabels (dict):
            mapping of port id to load name, e.g. {0:'arm_up',1:'arm_down'}
        board_id (int, default 0):
            board ID to connect to, set via jumpers on the board.
        '''
        self.devicetype = devicetype
        self.connection = connection
        self.deviceident = deviceident
        self.shared_device = shared_device

        if shared_device is not None:
            self.device_handle = shared_device.device_handle
        else:
            self.device_handle = ljm.openS(devicetype, connection, deviceident)
        self.num_relays = len(relaylabels)

        self.channel_to_label_map = self.labels = relaylabels
        self.label_to_channel_map = {val: key for key, val in self.channel_to_label_map.items()}
        self.state = {channel : False for channel in self.channel_to_label_map.keys()}

        # Sanitize labels: redo later
        atexit.register(self.setAllChannelsOff)

    def setAllChannelsOff(self):
        # with self.threadlock:
        print('Setting All Channels on LabJackRelay to Off')
        #maintain state, even if it's not used here
        self.state = {channel: False for channel in self.channel_to_label_map.keys()}
        try:
            self._refresh_board_state()
        except LJMError:
            self.device_handle = ljm.openS(self.devicetype, self.connection, self.deviceident)
            self._refresh_board_state()


    def setChannels(self, channels, verify=True):
        '''
        Write a value (True, False) to the channels specified in channels

        Parameters:
        channels (dict):
            dict of channels, keys as either str (name) or int (id) to write to, vals as the value to write
        '''
        # print(f'RUNNING SET CHANNELS WITH INPUT {channels}')

        print(f'Relay state change, CHANNELS = {channels}')
        for key, val in channels.items():
            try:
                converted_key = self.label_to_channel_map[key]
            except KeyError:
                raise KeyError(f'Labeled Channel not found: {key}. Configuration: {self.label_to_channel_map}')

            self.state[converted_key] = val

        self._refresh_board_state()
    def _refresh_board_state(self):
        names = list(self.state.keys())
        a_values = [int(not x) for x in self.state.values()]
        #~x is required to inverted logic since 0 = Channel is On = False
        ljm.eWriteNames(self.device_handle, self.num_relays, names, a_values)

        time.sleep(0.01)
        readback = [int(not x) for x in self.getChannels().values()]
        if not np.allclose(readback, a_values):
            retries = 0
            warnings.warn(f'ERROR: attempted relay set to {a_values} but readback was {readback}.')

            while retries < 60:
                ljm.eWriteNames(self.device_handle, self.num_relays, names, a_values)
                time.sleep(0.01)
                readback = [int(not x) for x in self.getChannels().values()]

                if np.allclose(readback, a_values):
                    print(f'Success after {retries+1} tries.')
                    break
                else:
                    retries = retries + 1

            if not np.allclose(readback, a_values):
                print(readback)
                print(a_values)
                raise Exception(f'Relay failed on cmd {self.state}, after {retries} attempts to correct')

    def getChannels(self, asid=False):
        '''
        Read the current state of all channels

        Parameters:
        asid (bool,default false):
        Dict keys should simply be the id, not the name.

        Returns:
        (dict) key:value mappings of state.
        '''

        CIO_names = ["CIO" + str(i) for i in range(4)]
        EIO_names = ["EIO" + str(i) for i in range(8)]
        CIO_results = ljm.eReadName(self.device_handle, "CIO_STATE")
        EIO_results = ljm.eReadName(self.device_handle, "EIO_STATE")
        CIO_dict = bitmask_to_dict(int(CIO_results), CIO_names)
        EIO_dict = bitmask_to_dict(int(EIO_results), EIO_names)

        IO_dict = {}
        IO_dict.update(CIO_dict)
        IO_dict.update(EIO_dict)

        retval = {}
        for channel in list(self.state.keys()):
            retval[self.channel_to_label_map[channel]] = not IO_dict[channel]

        return retval

    def toggleChannels(self, channels):
        #inverts
        for key in channels:
            converted_key = self.label_to_channel_map[key]
            self.state[converted_key] = ~self.state[converted_key]

        self._refresh_board_state()

def bitmask_to_dict(bitmask, keys):
    """
    Converts a boolean bitmask into a dictionary of booleans.

    :param bitmask: Integer bitmask
    :param keys: List of keys corresponding to each bit position
    :return: Dictionary with keys mapped to boolean values
    """
    return {key: bool(bitmask & (1 << i)) for i, key in enumerate(keys)}