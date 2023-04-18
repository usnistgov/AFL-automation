class DataPacket:
    
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
        if key in PROTECTED_SYSTEM_KEYS:
            self._system_dict[key] = value
        elif key in PROTECTED_SAMPLE_KEYS:
            self._sample_dict[key] = value
        else:
            self._transient_dict[key] = value
    
    def resetClass(self):
        self._transient_dict = {}
        
        
    def setupDefaults(self):
        pass
        
    def finalizeData(self):
        raise NotImplementedError
        
    def transmitData(self):
        raise NotImplementedError
