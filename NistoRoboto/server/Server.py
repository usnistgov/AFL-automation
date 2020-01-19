import opentrons.execute
from NistoRoboto.shared.utilities import listify


class Server:
    '''
    '''
    def __init__(self):
        self.protocol = opentrons.execute.get_protocol_api('2.0')

    def get_wells(self,loc):
        wells = []
        for loc in listify(source):
            if not (len(loc) == 3):
                raise ValueError(f'Well specification should be [SLOT][ROW_LETTER][COL_NUM] not {loc}')
            slot = loc[0]
            well = loc[1:]
            wells.append(self.protocol.loaded_labware[slot][well])

    def get_labware(self,slot):

    def transfer(self,mount,source,dest,volume,**kwargs):
        '''Transfer fluid from one location to another

        Arguments
        ---------
        mount: str ('left' or 'right')
            Mount location of pipette to be used

        source: str or list of str
            Source wells to transfer from. Wells should be specified as three
            character strings with the first character being the slot number.

        dest: str or list of str
            Destination wells to transfer from. Wells should be specified as
            three character strings with the first character being the slot
            number.

        volume: float
            volume of fluid to transfer

        '''

        #get pipette
        pipette = self.protocol.loaded_instruments[mount]

        #get source well
        if not isinstance(source,list):
            source = [source]

        source_wells = []
        for loc in source:
            slot = loc[0]
            well = loc[1:]
            source_wells.append(self.protocol.loaded_labware[slot][well])

        if not isinstance(dest,list):
            dest = [dest]

        dest_wells = []
        for loc in dest:
            slot = loc[0]
            well = loc[1:]
            dest_wells.append(self.protocol.loaded_labware[slot][well])

        pipette.transfer(volume,source,dest)








