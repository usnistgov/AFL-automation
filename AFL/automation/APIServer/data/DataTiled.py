from .DataPacket import DataPacket
import datetime
import json
import os
import tiled.client
import numpy as np
import copy

class DataTiled(DataPacket):
    '''
      A DataPacket implementation that serializes its data to Tiled
      with backup to JSON, named according to the current time.
    '''

    def __init__(self,server,api_key,backup_path):
        self.backup_path = backup_path
        self.tiled_client = tiled.client.from_uri(server,api_key=api_key)
        super().__init__()
        
        self.arrays = {}
        
    def finalize(self):
        self.transmit()
        self.reset()
        
    def add_array(self,array_name,array):
        self.arrays[array_name] = array
        
    def subtransmit_array(self,array_name,array):
        '''
        Transmits a numpy array along with all data in container and then clears the array from the container. All other data is preserved (no reset). 
        '''
        self._transient_dict['main_array'] = array
        self._transient_dict['array_name'] = array_name
        
        self._transmit()
        
        for name in ['main_array','array_name']:
            if name in self._transient_dict:
                del (self._transient_dict[name])
        
    def transmit(self):
        if 'main_array' in self._dict().keys():
            self.arrays['main_array'] = self._transient_dict['main_array']
            del(self._transient_dict['main_array'])
            
        if self.arrays:
            for array_name,array in self.arrays.items():
                # print(f'Attempting to add {array_name} of dtype {array.dtype} and size {array.size}')
                self.subtransmit_array(array_name,array)
            self.arrays = {}
        else:
            self._transmit()
        
            
    def _transmit(self):
        '''
            Transmits the data inside this container to Tiled.

            If a tiled connection fails or is not possible, serializes to JSON,
            named according to the current time.

        '''
        
        try:
            if 'main_array' in self._dict().keys():
                main_data = copy.deepcopy(self._dict()['main_array'])
                del(self._transient_dict['main_array'])
                fxn = self.tiled_client.write_array
            elif 'main_dataframe' in self._dict().keys():
                main_data = copy.deepcopy(self._dict()['main_dataframe'])
                del(self._transient_dict['main_dataframe'])
                fxn = self.tiled_client.write_dataframe
            else:
                main_data = [np.nan]
                fxn = self.tiled_client.write_array
            #self._print_dict_member_types(self._dict())
            self._sanitize()
            #print(self._dict())
            #self._print_dict_member_types(self._dict())
            fxn(main_data,metadata =self._dict())
        except Exception as e:
            print(f'Exception while transmitting to Tiled! {e}. Saving data in backup store.')
            if type(main_data) == np.ndarray:
                self['main_data'] = main_data.tolist()
            self._sanitize()
            
            filename = str(datetime.datetime.now()).replace(' ','-')
            with open(f'{self.backup_path}/{filename}.json','w') as f:
                json.dump(self._dict(),f)

