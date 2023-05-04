from .DataPacket import DataPacket
import datetime
import json
import os
import tiled.client
import numpy as np

class DataTiled(DataPacket):
    '''
      A DataPacket implementation that serializes its data to Tiled
      with backup to JSON, named according to the current time.
    '''

    def __init__(self,server,api_key,backup_path):
        self.backup_path = backup_path
        self.tiled_client = tiled.client.from_uri(server,api_key=api_key)
        super().__init__()
    def finalize(self):
        self.transmit()
        self.reset()
    def transmit(self):
        '''
            Transmits the data inside this container to Tiled.

            If a tiled connection fails or is not possible, serializes to JSON,
            named according to the current time.

        '''

        
        try:
            if 'main_array' in self._dict().keys():
                main_data = self._dict()['main_array']
                fxn = self.tiled_client.write_array
            elif 'main_dataframe' in self._dict().keys():
                main_data = self._dict()['main_dataframe']
                fxn = self.tiled_client.write_dataframe
            else:
                main_data = [self._dict()['meta']['return_val']]
                fxn = self.tiled_client.write_array
            #self._print_dict_member_types(self._dict())
            self._sanitize()
            #print(self._dict())
            #self._print_dict_member_types(self._dict())
            fxn(main_data,metadata =self._dict())
        except Exception as e:
            print(f'Exception while transmitting to Tiled! {e}. Saving data in backup store.')
            self._sanitize()
            filename = str(datetime.datetime.now()).replace(' ','-')
            with open(f'{self.backup_path}/{filename}.json','w') as f:
                json.dump(self._dict(),f)

