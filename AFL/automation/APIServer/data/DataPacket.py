import copy
from collections.abc import MutableMapping

class DataPacket(MutableMapping):
    
    PROTECTED_SYSTEM_KEYS = [
        'driver_name',
        'driver_config',
        'platform_serial',
        
        
    
    ]
    PROTECTED_SAMPLE_KEYS = [
        'sample_name',
        'sample_uuid',
        'sample_composition',
        'sample_al_components',
        
    
    ]
    
    def __init__(self):
        self._transient_dict = {}
        self._system_dict = {}
        self._sample_dict = {}
        
    def __getitem__(self,key):
        if key in self._system_dict.keys():
            return self._system_dict[key]
        elif key in self._sample_dict.keys():
            return self._sample_dict[key]
        else:
            return self._transient_dict[key]
    
    def __setitem__(self,key,value):
        if key in self.PROTECTED_SYSTEM_KEYS:
            self._system_dict[key] = value
        elif key in self.PROTECTED_SAMPLE_KEYS:
            self._sample_dict[key] = value
        else:
            self._transient_dict[key] = value
    def __delitem__(self,key):
        if key in self.PROTECTED_SYSTEM_KEYS:
            self._system_dict.__delitem__(key)
        elif key in self.PROTECTED_SAMPLE_KEYS:
            self._sample_dict.__delitem__(key)
        else:
            self._transient_dict.__delitem__(key)
    def __len__(self):
        return len(self._system_dict)+len(self._sample_dict)+len(self._transient_dict)

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
    def reset(self):
        self._transient_dict = {}
    
    def keys(self):
        return self._transient_dict.keys() |  self._sample_dict.keys() |  self._system_dict.keys()
        
    def setupDefaults(self):
        pass
        
    def finalize(self):
        self.transmit()
        self.reset()
        
    def transmit(self):
        raise NotImplementedError
