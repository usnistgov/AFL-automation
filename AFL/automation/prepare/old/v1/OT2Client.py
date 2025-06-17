import requests
from AFL.automation.APIServer.Client import Client
from AFL.automation.prepare.PipetteAction import PipetteAction

class OT2Client(Client):
    '''Communicate with AFL-automation server on OT-2

    This class maps pipettor functions to HTTP REST requests that are sent to
    the AFL-automation server
    '''
    def transfer(self,
            source,
            dest,
            volume,
            interactive=None,
            **kwargs
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
        json = {'task_name':'transfer'}
        json.update(PipetteAction(source=source,dest=dest,volume=volume,**kwargs).get_kwargs())

        UUID = self.enqueue(interactive=interactive,**json)
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
