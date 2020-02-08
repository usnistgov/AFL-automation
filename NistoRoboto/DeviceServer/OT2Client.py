import requests
from NistoRoboto.DeviceServer.Client import Client

class OT2Client(Client):
    '''Communicate with NistoRoboto server on OT-2

    This class maps pipettor functions to HTTP REST requests that are sent to
    the NistoRoboto server
    '''
    def transfer(self,source,dest,volume,source_loc=None,dest_loc=None):
        '''Transfer fluid from one location to another

        Arguments
        ---------
        source: str or list of str
            Source wells to transfer from. Wells should be specified as three
            character strings with the first character being the slot number.

        dest: str or list of str
            Destination wells to transfer from. Wells should be specified as
            three character strings with the first character being the slot
            number.

        volume: float
            volume of fluid to transfer in microliters

        '''
        json = {}
        json['task_name']  = 'transfer'
        json['source'] = source
        json['dest']   = dest
        json['volume'] = volume
        if source_loc is not None:
            json['source_loc'] = source_loc
        if dest_loc is not None:
            json['dest_loc'] = dest_loc
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to transfer command failed with status_code {response.status_code}\n{response.content}')

    def load_labware(self,name,slot):
        json = {}
        json['task_name']  = 'load_labware'
        json['name'] = name
        json['slot'] = slot
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to load_labware command failed with status_code {response.status_code}\n{response.content}')

    def load_instrument(self,name,mount,tip_rack_slots):
        json = {}
        json['task_name']  = 'load_instrument'
        json['name'] = name
        json['mount'] = mount
        json['tip_rack_slots'] = tip_rack_slots
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to load_instrument command failed with status_code {response.status_code}\n{response.content}')

    def home(self):
        json = {}
        json['task_name']  = 'home'
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to home command failed with status_code {response.status_code}\n{response.content}')
