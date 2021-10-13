import requests
from NistoRoboto.APIServer.client.Client import Client

class OT2Client(Client):
    '''Communicate with NistoRoboto server on OT-2

    This class maps pipettor functions to HTTP REST requests that are sent to
    the NistoRoboto server
    '''
    def transfer(self,
            source,
            dest,
            volume,
            source_loc=None,
            dest_loc=None,
            mix_before=None,
            air_gap=0,
            aspirate_rate=None,
            dispense_rate=None,
            post_aspirate_delay=0.0,
            post_dispense_delay=0.0,
            blow_out=False,
            ):
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
        json['air_gap'] = air_gap
        json['blow_out'] = blow_out
        if source_loc is not None:
            json['source_loc'] = source_loc
        if dest_loc is not None:
            json['dest_loc'] = dest_loc
        json['aspirate_rate']=aspirate_rate
        json['dispense_rate']=dispense_rate
        json['post_aspirate_delay']=post_aspirate_delay
        json['post_dispense_delay']=post_dispense_delay

        UUID = self.enqueue(**json)
        return UUID
    
    def reset_tipracks(self,mount='both'):
        json = {}
        json['task_name']  = 'reset_tipracks'
        json['mount'] = mount
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

    def aspirate_rate(self,rate):
        json = {}
        json['task_name']  = 'set_aspirate_rate'
        json['rate']  = rate
        UUID = self.enqueue(**json)
        return UUID

    def dispense_rate(self,rate):
        json = {}
        json['task_name']  = 'set_dispense_rate'
        json['rate']  = rate
        UUID = self.enqueue(**json)
        return UUID

    def home(self):
        json = {}
        json['task_name']  = 'home'
        UUID = self.enqueue(**json)
        return UUID
