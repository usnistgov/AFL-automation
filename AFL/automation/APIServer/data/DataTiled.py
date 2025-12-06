from .DataPacket import DataPacket
import datetime
import json
import os
import tiled.client
from tiled.client.xarray import write_xarray_dataset
import numpy as np
import xarray as xr
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
        if 'main_dataset' in self._dict().keys():
            # main_dataset is handled directly in _transmit, no need to move to arrays dict
            self._transmit()
            return
        
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
            if 'main_dataset' in self._dict().keys():
                main_data = copy.deepcopy(self._dict()['main_dataset'])
                del(self._transient_dict['main_dataset'])
                # Sanitize internal dicts first
                self._sanitize()
                # Get sanitized metadata from DataPacket
                metadata = self._dict()
                # Merge DataPacket metadata into dataset.attrs so it becomes searchable
                # write_xarray_dataset stores dataset.attrs in metadata['attrs']
                if not hasattr(main_data, 'attrs'):
                    main_data.attrs = {}
                # Update dataset attrs with DataPacket metadata
                main_data.attrs.update(metadata)
                # Write using native Tiled xarray support
                write_xarray_dataset(self.tiled_client, main_data)
            elif 'main_array' in self._dict().keys():
                main_data = copy.deepcopy(self._dict()['main_array'])
                array_name = self._transient_dict.get('array_name', 'main_array')
                del(self._transient_dict['main_array'])
                if 'array_name' in self._transient_dict:
                    del(self._transient_dict['array_name'])
                # Convert numpy array to xarray Dataset
                # Create dimension names based on array shape
                dims = [f'dim_{i}' for i in range(main_data.ndim)]
                dataset = xr.Dataset({array_name: (dims, main_data)})
                # Sanitize internal dicts first
                self._sanitize()
                # Get sanitized metadata from DataPacket
                metadata = self._dict()
                # Merge DataPacket metadata into dataset.attrs so it becomes searchable
                # write_xarray_dataset stores dataset.attrs in metadata['attrs']
                if not hasattr(dataset, 'attrs'):
                    dataset.attrs = {}
                # Update dataset attrs with DataPacket metadata
                dataset.attrs.update(metadata)
                # Write using native Tiled xarray support
                write_xarray_dataset(self.tiled_client, dataset)
            elif 'main_dataframe' in self._dict().keys():
                main_data = copy.deepcopy(self._dict()['main_dataframe'])
                del(self._transient_dict['main_dataframe'])
                fxn = self.tiled_client.write_dataframe
                self._sanitize()
                fxn(main_data, metadata=self._dict())
            else:
                main_data = [np.nan]
                fxn = self.tiled_client.write_array
                self._sanitize()
                fxn(main_data, metadata=self._dict())
        except Exception as e:
            print(f'Exception while transmitting to Tiled! {e}. Saving data in backup store.')
            if 'main_data' not in locals():
                if 'main_dataset' in self._dict().keys():
                    # For datasets, try to serialize key info
                    try:
                        dataset = self._dict()['main_dataset']
                        self['main_data'] = {'type': 'xarray.Dataset', 'variables': list(dataset.data_vars.keys())}
                    except:
                        self['main_data'] = 'xarray.Dataset'
                elif 'main_array' in self._dict().keys():
                    main_data = self._dict()['main_array']
                    if isinstance(main_data, np.ndarray):
                        self['main_data'] = main_data.tolist()
                    else:
                        self['main_data'] = str(main_data)
            self._sanitize()
            
            filename = str(datetime.datetime.now()).replace(' ','-')
            with open(f'{self.backup_path}/{filename}.json','w') as f:
                json.dump(self._dict(),f)

