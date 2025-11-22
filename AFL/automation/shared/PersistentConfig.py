import json
import datetime
import pathlib
import copy
import warnings
import threading
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
        max_history_size_mb=100,  # New: limit history by file size
        write_debounce_seconds=0.1,  # New: batch writes within this time window
        compact_json=True,  # New: use compact JSON for large files
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
        
        max_history: int
            Maximum number of history entries to keep (default: 10000)
            
        max_history_size_mb: float
            Maximum size of history file in MB. If exceeded, oldest entries are removed.
            Set to None to disable size-based limiting. (default: 100 MB)
            
        write_debounce_seconds: float
            Delay in seconds before writing to disk after a change. Multiple rapid
            changes will be batched into a single write. Set to 0 to disable debouncing.
            (default: 0.1 seconds)
            
        compact_json: bool
            If True, use compact JSON (no indentation) for files larger than 1MB.
            This significantly reduces file size and write time for large configs.
            (default: True)
        
        datetime_key_format: str
            String defining the root level keys of the json-serialized file. 
            See https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior.
        '''
        self.path = pathlib.Path(path)
        self.datetime_key_format = datetime_key_format
        self.write = write  
        self.lock = False  # In case of True, only lock configuration at end of constructor
        self.max_history = max_history
        self.max_history_size_mb = max_history_size_mb
        self.write_debounce_seconds = write_debounce_seconds
        self.compact_json = compact_json
        
        # Debouncing state
        self._pending_write = False
        self._write_timer = None
        self._write_lock = threading.Lock()
        
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
            self._update_history(immediate=True)  # Immediate write during init
            
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
        self._update_history(immediate=True)  # Immediate write for revert
    
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
    
    def flush(self):
        '''Force immediate write to disk, bypassing debouncing'''
        with self._write_lock:
            if self._write_timer is not None:
                self._write_timer.cancel()
                self._write_timer = None
            self._pending_write = False
            self._do_write()
    
    def _estimate_history_size_mb(self):
        '''Estimate the size of history in MB by serializing to JSON'''
        try:
            # Use compact JSON for size estimation
            json_str = json.dumps(self.history, separators=(',', ':'))
            return len(json_str.encode('utf-8')) / (1024 * 1024)
        except Exception:
            # Fallback: rough estimate based on number of entries
            return len(self.history) * 0.01  # Assume ~10KB per entry
    
    def _trim_history_by_size(self):
        '''Remove oldest history entries until file size is under limit'''
        if self.max_history_size_mb is None:
            return
            
        while self._estimate_history_size_mb() > self.max_history_size_mb:
            keys = self._get_sorted_history_keys()
            if len(keys) <= 1:  # Keep at least one entry
                break
            # Remove oldest entry
            del self.history[keys[0]]
    
    def _do_write(self):
        '''Perform the actual write to disk'''
        if not self.write:
            return
            
        # Trim history by count
        if len(self.history) > self.max_history:
            keys = self._get_sorted_history_keys()
            # delete all keys more than max history
            for key in keys[:-self.max_history]:
                del self.history[key]
        
        # Trim history by size
        self._trim_history_by_size()
        
        # Add current config to history
        key = self._get_datetime_key()
        self.history[key] = copy.deepcopy(self.config)
        
        # Determine if we should use compact JSON
        use_compact = self.compact_json and self._estimate_history_size_mb() > 1.0
        
        # Atomic write: write to temp file, then rename
        temp_path = self.path.with_suffix(self.path.suffix + '.tmp')
        try:
            with open(temp_path, 'w') as f:
                if use_compact:
                    # Compact JSON for large files
                    json.dump(self.history, f, separators=(',', ':'))
                else:
                    # Pretty-printed JSON for small files (easier to read/debug)
                    json.dump(self.history, f, indent=4)
            
            # Atomic rename
            temp_path.replace(self.path)
        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise e
    
    def _schedule_write(self):
        '''Schedule a debounced write'''
        if self.write_debounce_seconds <= 0:
            # No debouncing, write immediately
            self._do_write()
            return
            
        with self._write_lock:
            self._pending_write = True
            
            # Cancel existing timer if any
            if self._write_timer is not None:
                self._write_timer.cancel()
            
            # Schedule new write
            def delayed_write():
                with self._write_lock:
                    if self._pending_write:
                        self._pending_write = False
                        self._write_timer = None
                        self._do_write()
            
            self._write_timer = threading.Timer(self.write_debounce_seconds, delayed_write)
            self._write_timer.start()
    
    def _update_history(self, immediate=False):
        '''Update history and optionally write to disk
        
        Parameters
        ----------
        immediate: bool
            If True, write immediately without debouncing. Used for initialization
            and critical operations like revert.
        '''
        if self.write:
            if immediate or self.write_debounce_seconds <= 0:
                self._do_write()
            else:
                self._schedule_write()
        else:
            warnings.warn(
                '''
                PersistentConfig writing disabled. To save changes to config, 
                set self.write to True.
                ''' 
            )
