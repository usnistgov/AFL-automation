import copy
from collections.abc import MutableMapping

import numpy as np
import pandas as pd


class DataPacket(MutableMapping):
    '''
    A DataPacket is a container for data that is to be transmitted to a data store.

    It is a dictionary-like object that stores data in three different ways:
    - transient data, which is cleared on resets
    - system data, which is never cleared
    - sample data, which is cleared only on specific resets of the sample

    The data is transmitted to the data store on finalization, which is called at the end of each method.
    '''

    PROTECTED_SYSTEM_KEYS = [
        'driver_name',
        'driver_config',
        'platform_serial',

    ]
    PROTECTED_SAMPLE_KEYS = [
        'sample_name',
        'sample_uuid',
        'sample_composition',
        'AL_components',
        'AL_campaign_name',
        'AL_uuid',
    ]

    def __init__(self):
        self._transient_dict = {}
        self._system_dict = {}
        self._sample_dict = {}

    def __getitem__(self, key):
        if key in self._system_dict.keys():
            return self._system_dict[key]
        elif key in self._sample_dict.keys():
            return self._sample_dict[key]
        else:
            return self._transient_dict[key]

    def __setitem__(self, key, value):
        if key in self.PROTECTED_SYSTEM_KEYS:
            self._system_dict[key] = value
        elif key in self.PROTECTED_SAMPLE_KEYS:
            self._sample_dict[key] = value
        else:
            self._transient_dict[key] = value

    def __delitem__(self, key):
        if key in self.PROTECTED_SYSTEM_KEYS:
            self._system_dict.__delitem__(key)
        elif key in self.PROTECTED_SAMPLE_KEYS:
            self._sample_dict.__delitem__(key)
        else:
            self._transient_dict.__delitem__(key)

    def __len__(self):
        return len(self._system_dict) + len(self._sample_dict) + len(self._transient_dict)

    def __iter__(self):
        yield from self._system_dict
        yield from self._sample_dict
        yield from self._transient_dict

    def _dict(self):
        ''' 
        returns a single dictionary that contains all values stored in data.
        
        N.B.: this dict is a deepcopy of the internal structures, so it cannot be written to - or at least, if it is, those writes will be lost.
        
        '''
        retval = copy.deepcopy(self._transient_dict)
        retval.update(self._sample_dict)
        retval.update(self._system_dict)
        return retval

    def _core_sanitize(self, to_sanitize):
        '''
        Inner worker function to make sure that all values in a dictionary are JSON-serializable.
        '''
        output_dict = copy.deepcopy(to_sanitize)

        for key in to_sanitize.keys():
            if isinstance(to_sanitize[key], (list, tuple)):
                # print(f'Sanitized list/tuple {key}')
                output_dict[key] = list(to_sanitize[key])
            elif isinstance(to_sanitize[key], (int, float, str, bool)):
                # print(f'No need to sanitize primitive {key}')
                pass
            elif isinstance(to_sanitize[key], np.ndarray):
                # print(f'Sanitized ndarray {key}')
                output_dict[key] = to_sanitize[key].tolist()
            elif isinstance(to_sanitize[key], pd.DataFrame):
                # print(f'Sanitized dataframe {key}')
                output_dict[key] = to_sanitize[key].tojson()
            elif isinstance(to_sanitize[key], dict):
                # print(f'Sanitized dict {key}')
                output_dict[key] = self._core_sanitize(to_sanitize[key])
            else:
                # print(f'Sanitized fallback to string {key}')
                output_dict[key] = str(to_sanitize[key])

        return output_dict

    def _print_dict_member_types(self, input, prefix=''):
        for key in input.keys():
            print(f'{prefix} {key} is of type {type(input[key])}')
            if type(input[key]) is dict:
                self._print_dict_member_types(input[key], prefix=f'{prefix} -->')

    def _sanitize(self):
        '''
        Sanitize the contents of the packet to be JSON-serializable.

        '''

        self._transient_dict = self._core_sanitize(self._transient_dict)
        self._sample_dict = self._core_sanitize(self._sample_dict)
        self._system_dict = self._core_sanitize(self._system_dict)

    def reset(self):
        '''
        Clears all transient data.
        '''
        self._transient_dict = {}

    def keys(self):
        return self._transient_dict.keys() | self._sample_dict.keys() | self._system_dict.keys()

    def setupDefaults(self):
        pass

    def finalize(self):
        self.transmit()
        self.reset()

    def reset_sample(self):
        self._sample_dict = {}

    def transmit(self):
        raise NotImplementedError

    def add_array(self):
        '''Abstract method adding arrays that need special handling'''
        raise NotImplementedError
