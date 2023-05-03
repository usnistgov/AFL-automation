from .DataPacket import DataPacket
import datetime
import json
import os
import tiled

class DataTiled(DataPacket):
    '''
      A DataPacket implementation that serializes its data to Tiled
      with backup to JSON, named according to the current time.
    '''

    def __init__(self,server,api_key,backup_path):
        self.backup_path = backup_path
        self.tiled_client = tiled.client.from_uri(server,api_key=api_key)
        super().__init__()
    def transmitData(self):
        '''
            Transmits the data inside this container to Tiled.

            If a tiled connection fails or is not possible, serializes to JSON,
            named according to the current time.

        '''
        try:
            if 'main_array' in data.keys():
                self.tiled_client.write_array(data['main_array'],metadata=self._dict())
            elif 'main_dataframe' in data.keys():
                self.tiled_client.write_dataframe(data['main_dataframe'],metadata=self._dict())
            else:
                self.tiled_client.write_array([np.nan],metadata=self._dict())
        except Exception:
            filename = str(datetime.datetime.now()).replace(' ','-')
            with open(f'{self.backup_path}/{filename}.json','w') as f:
                json.dump(self._dict(),f)

