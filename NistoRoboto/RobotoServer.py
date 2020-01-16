import opentrons.execute


class RobotoServer:
    '''
    '''
    def __init__(self):
        self.protocol = None#opentrons.execute.get_protocol_api('2.0')

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
            destination wells to transfer to

        volume: float
            volume of fluid to transfer

        '''

        if self.protocol is None:
            print('mount:',mount)
            print('source:',source)
            print('dest:',dest)
            print('volume:',volume)
            return 'success'

        #get pipette
        pipette = self.protocol.loaded_instruments[mount]

        #get source well
        if not isinstance(source,list):
            source = [source]

        source_wells = []
        for loc in source:
            slot = loc[0]
            well = loc[1:]
            wells.append(self.protocol.loaded_labware[slot][well])

        if not isinstance(dest,list):
            dest = [dest]

        dest_wells = []
        for loc in dest:
            slot = loc[0]
            well = loc[1:]
            wells.append(self.protocol.loaded_labware[slot][well])

        pipette.transfer(volume,source,dest)








