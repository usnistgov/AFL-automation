import json
import datetime
import pathlib
import copy
import warnings
from collections.abc import MutableMapping

class PersistentConfig(MutableMapping):
    ''' A dictionary-like class that serializes changes to disk
    
    This class provides dictionary-like setters and getters (e.g., [] and 
    .update()) but, by default, all modifications are written into a file in 
    json format with the root keys as timestamps. Modifications can be blocked 
    by locking the config, and writing  to disk can be disabled by setting the 
    appropriate member attributes (see constructor). On instantiation, if
    provided with a previously saved configuration file, PersistentConfig will
    load the file's contents into memory and use the more recent configuration.
    '''
    def __init__( 
        self, 
        path, 
        defaults=None, 
        overrides=None, 
        lock=False,
        write=True,
        max_history=10000,
        datetime_key_format='%y/%d/%m %H:%M:%S.%f'
                ):
        '''Constructor
        
        Parameters
        ---------
        path: str or pathlib.Path
            File path to file in which this config is or will be stored. This 
            file will be created if it does not exist
        
        defaults: dict
            Default values to use if no saved config is available or if 
            parameters are missing from a saved config.
            
        overrides: dict
            Values to use that override parameters in a saved config. These 
            parameters can be changed after the PersistentConfig object is 
            instantiated.
        
        lock: bool
            If True, an AttributeError will be raised if the user attempts to 
            modify the config
            
        write: bool
            If False, all writing to the config file will be disabled and a 
            warning will be emitted each time the config is modified.
        
        datetime_key_format: str
            String defining the root level keys of the json-serialized file. 
            See https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior.
        '''
        self.path = pathlib.Path(path)
        self.datetime_key_format = datetime_key_format
        self.write = write  
        self.lock = False  # In case of True, only lock configuration at end of constructor
        self.max_history = max_history
        
        need_update=False
        if self.path.exists():
            with open(self.path,'r') as f:
                self.history = json.load(f)
            key = self._get_sorted_history_keys()[-1] #use latest key
            self.config = copy.deepcopy(self.history[key])
        else:
            self.config = {}
            self.history = {self._get_datetime_key():{}}
            need_update=True
        
        if defaults is not None:
            #cannot use .update because we don't want to clobber existing values
            for k,v in defaults.items():
                if k not in self.config:
                    self.config[k] = v
                    need_update=True
                    
        if overrides is not None:
            #use dict.update method rather than PersistentConfig.update
            self.config.update(overrides)
            need_update=True
                    
        if need_update:
            self._update_history()
            
        self.lock = lock #In case of True, only lock configuration at end of constructor
                
    def __str__(self):
        return f'<PersistentConfig entries: {len(self.config)} last_saved: {self._get_sorted_history_keys()[-1]}>'
    
    def __repr__(self):
        return self.__str__()
    
    def __getitem__(self,key):
        '''Dictionary-like getter via config["param"]'''
        return self.config[key]
    
    def __setitem__(self,key,value): 
        '''Dictionary-like setter via config["param"]=value
        
        Changes will be written to PersistentConfig.path if PersistentConfig.write 
        is True (default).
        '''
        if self.lock:
            raise AttributeError(
                '''
                Attempting to change locked config. Set self.lock to False to 
                make changes to config.
                ''' 
            )
            
        self.config[key] = value
        self._update_history()

    def toJSON(self):
        '''
        Serialize the config to json
        '''
        return json.dumps(self.config)
        
    def __iter__(self):
        for key,value in self.config.items():
            yield key,value
    def __len__(self):
        return len(self.config)
    def __delitem__(self,key):
        del self.config[key]
        self._update_history()
        
    def update(self,update_dict): 
        '''Update several values in config at once
        
        Changes will be written to PersistentConfig.path if PersistentConfig.write 
        is True (default).
        '''
        if self.lock:
            raise AttributeError(
                '''
                Attempting to change locked config. Set self.lock to False to 
                make changes to config.
                ''' 
            )
        self.config.update(update_dict)
        self._update_history()
        
    def revert(self,nth=None,datetime_key=None):
        '''Revert config to a historical config
        
        Parameters
        ----------
        nth: int, **optional***
            Integer index of historical value to revert to. Can be negative to count from end of 
            history. Note that -1 will correspond to the current config.
        
        datetime_key: str, **optional**
            datetime formatted string as defined by datetime_key_format
        '''
        if nth is not None:
            key = list(self._get_sorted_history_keys())[nth] #supports negative indexing
        elif datetime_key is not None:
            key = datetime_key
        else:
            raise ValueError('Must supply nth or datetime_key!')
        self.config = copy.deepcopy(self.history[key])
        self._update_history()
    
    def get_historical_values(self,key,convert_to_datetime=False):
        '''Convenience method for gathering historical values of a parameter
        '''
        dates = []
        values = []
        for date,config in self.history.items():
            if key in config:
                if convert_to_datetime:
                    dates.append(self._decode_datetime_key(date))
                else:
                    dates.append(date)
                values.append(config[key])
        return dates,values
            
        
        
    def _get_datetime_key(self):
        return datetime.datetime.now().strftime(self.datetime_key_format)
    
    def _decode_datetime_key(self,key):
        return datetime.datetime.strptime(key,self.datetime_key_format)
    
    def _encode_datetime_key(self,key):
        return datetime.datetime.strftime(key,self.datetime_key_format)
    
    def _get_sorted_history_keys(self):
        #get latest key by converting to datetime object
        keys = sorted(map(self._decode_datetime_key,self.history.keys()))
            
        #convert back to formatted string
        keys = list(map(self._encode_datetime_key,keys))
            
        return keys
    
    def _update_history(self):
        if self.write:
            if len(self.history)>self.max_history:
                keys = self._get_sorted_history_keys()
                #print(f'History reached max # of entries ( removing oldest key: {keys[0]}')
                # delete all keys more than max history
                for key in keys[:-self.max_history]:
                    del self.history[key]
            key = self._get_datetime_key()
            self.history[key] = copy.deepcopy(self.config)
            with open(self.path,'w') as f:
                json.dump(self.history,f,indent=4)
        else:
            warnings.warn(
                '''
                PersistentConfig writing disabled. To save changes to config, 
                set self.write to True.
                '''
            )
