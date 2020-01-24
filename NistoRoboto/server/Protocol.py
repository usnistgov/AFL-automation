import opentrons.execute

class Protocol:
    def __init__(self,app):
        self._app = app
        self.protocol = opentrons.execute.get_protocol_api('2.0')

    def reset(self):
        self._app.logger.info('Resetting the protocol context')

        raise NotImplementedError('This method doesn\'t work yet. For now, just restart the flask server')

        #XXX HACK! asyncio event loop finding borks without this
        # self._app.logger.debug(opentrons.execute._HWCONTROL)
        # del opentrons.execute._HWCONTROL
        # opentrons.execute._HWCONTROL = None
        self._app.logger.debug(opentrons.execute._HWCONTROL)

        self.protocol = opentrons.execute.get_protocol_api('2.0')

    def home(self):
        self._app.logger.info('Homing the robots axes')
        self.protocol.home()

    def get_wells(self,locs):
        self._app.logger.debug(f'Converting locations to well objects: {loc}')
        wells = []
        for loc in listify(locs):
            if not (len(loc) == 3):
                raise ValueError(f'Well specification should be [SLOT][ROW_LETTER][COL_NUM] not \'{loc}\'')
            slot = loc[0]
            well = loc[1:]
            labware = self.get_labware(slot)
            wells.append(labware[well])
        self._app.logger.debug(f'Created well objects: {wells}')
        return wells

    def get_labware(self,slot):
        self._app.logger.debug(f'Getting labware from slot \'{slot}\'')
        if self.protocol.deck[slot] is not None:
            labware = self.protocol.deck[slot]
            self._app.logger.debug(f'Found labware \'{labware}\'')
            return labware
        else:
            raise ValueError('Specified slot ({slot}) is empty of labware')

    def load_labware(self,name,slot,**kw):
        '''Load labware (containers,tipracks) into the protocol'''
        self._app.logger.debug(f'Loading labware \'{name}\' into slot \'{slot}\' into the protocol context')
        self.protocol.load_labware(name,slot)

    def load_instrument(self,name,mount,tip_rack_slots,**kw):
        '''Load a pipette into the protocol'''
        self._app.logger.debug(f'Loading pipette \'{name}\' into mount \'{mount}\' with tip_racks in slots {tip_rack_slots}')
        tip_racks = []
        for slot in listify(tip_rack_slots):
            tip_rack = self.protocol.deck[slot]
            if not tip_rack.is_tiprack:
                raise RuntimeError('Supplied slot doesn\'t contain a tip_rack!')
            tip_racks.append(tip_rack)
        self.protocol.load_instrument(name,mount,tip_racks=tip_racks)

    def transfer(self,source,dest,volume,**kwargs):
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
            volume of fluid to transfer

        '''
        self._app.logger.info(f'Transfering {volume}uL from {source} to {dest}')

        #get pipette based on volume
        pipette = self.get_pipette(volume)
        source_wells = self.get_wells(source)
        dest_wells = self.get_wells(dest)
        pipette.transfer(volume,source_wells,dest_wells)

    def get_pipette(self,volume):
        self._app.logger.debug(f'Looking for a pipette for volume {volume}')
        found_pipettes = []
        minVolStr = ''
        for mount,pipette in self.protocol.loaded_instruments.items():
            minVolStr += f'{pipette.min_volume}>{volume}\\n'
            if volume>pipette.min_volume:
                found_pipettes.append(pipette)
    
        self._app.logger.debug(f'Found pipettes with suitable minimum volume: {pipettes}')
        if not found_pipettes:
            raise ValueError('No suitable pipettes found!\\n'+ minVolStr)
        
        pipette = min(found_pipettes,key=lambda x: x.max_volume)
        self._app.logger.debug(f'Chosen pipette: {pipette}')
        return pipette
