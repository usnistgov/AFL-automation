import requests
from NistoRoboto.DeviceServer.Client import Client

class OT2Client(Client):
    '''Communicate with NistoRoboto server on OT-2

    This class maps pipettor functions to HTTP REST requests that are sent to
    the NistoRoboto server
    '''
    def transfer(self,source,dest,volume,source_loc=None,dest_loc=None,mix_before=None):
        '''Transfer fluid from one location to another

        Arguments
        ---------
        source: str or list of str Source wells to transfer from. Wells should be specified as three
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
        json['mix_before'] = mix_before
        if source_loc is not None:
            json['source_loc'] = source_loc
        if dest_loc is not None:
            json['dest_loc'] = dest_loc

        UUID = self.enqueue(**json)
        return UUID

    def load_labware(self,name,slot):
        json = {}
        json['task_name']  = 'load_labware'
        json['name'] = name
        json['slot'] = slot
        UUID = self.enqueue(**json)
        return UUID

    def load_instrument(self,name,mount,tip_rack_slots):
        json = {}
        json['task_name']  = 'load_instrument'
        json['name'] = name
        json['mount'] = mount
        json['tip_rack_slots'] = tip_rack_slots
        UUID = self.enqueue(**json)
        return UUID

    def home(self):
        json = {}
        json['task_name']  = 'home'
        UUID = self.enqueue(**json)
        return UUID
