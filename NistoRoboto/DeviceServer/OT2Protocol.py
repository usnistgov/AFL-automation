import opentrons.execute
import opentrons
from NistoRoboto.DeviceServer.Protocol import Protocol
from NistoRoboto.shared.utilities import listify
from math import ceil,sqrt

class OT2Protocol(Protocol):
    def __init__(self):
        self.app = None
        self.name = 'OT2Protocol'
        self.protocol = opentrons.execute.get_protocol_api('2.0')

    def reset(self):
        self._app.logger.info('Resetting the protocol context')

        raise NotImplementedError('This method doesn\'t work yet. For now, just restart the flask server')

        # opentrons.robot.reset() doesnt work

        # #XXX HACK! asyncio event loop finding borks without this
        # # self._app.logger.debug(opentrons.execute._HWCONTROL)
        # # del opentrons.execute._HWCONTROL
        # # opentrons.execute._HWCONTROL = None
        # self._app.logger.debug(opentrons.execute._HWCONTROL)

        # self.protocol = opentrons.execute.get_protocol_api('2.0')

    def home(self):
        self._app.logger.info('Homing the robot\'s axes')
        self.protocol.home()

    def get_wells(self,locs):
        self._app.logger.debug(f'Converting locations to well objects: {locs}')
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
        if self.protocol.deck[slot] is not None:
            if self.protocol.deck[slot].name == name:
                self._app.logger.info(f'Labware \'{name}\' already loaded into slot \'{slot}\'.\n')
                #do nothing
            else:
                raise RuntimeError(f'''Attempted to load labware \'{name}\' into slot \'{slot}\'.
                        Slot is already filled loaded with {self.protocol.deck[slot]}.''')
        else: 
            self._app.logger.debug(f'Loading labware \'{name}\' into slot \'{slot}\' into the protocol context')
            self.protocol.load_labware(name,slot)

    def load_instrument(self,name,mount,tip_rack_slots,**kw):
        '''Load a pipette into the protocol'''

        if mount in self.protocol.loaded_instruments:
            if self.protocol.loaded_instruments[mount].name == name:
                self._app.logger.info(f'Instrument \'{name}\' already loaded into mount \'{mount}\'.\n')
                #do nothing
            else:
                raise RuntimeError(f'''Attempted to load instrument \'{name}\' into mount \'{mount}\'.
                        mount is already loaded with {self.protocol.loaded_instruments[mount]}.''')
        else: 
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

        #modify source well dispense location
        source_wells = self.get_wells(source)
        if 'source_loc' in kwargs:
            source_wells = [getattr(sw,kwargs['source_loc'])() for sw in source_wells]


        #modify destination well dispense location
        dest_wells = self.get_wells(dest)
        if 'dest_loc' in kwargs:
            dest_wells = [getattr(dw,kwargs['dest_loc'])() for dw in dest_wells]

        pipette.transfer(volume,source_wells,dest_wells)

    def get_pipette(self,volume,method='min_transfers'):
        self._app.logger.debug(f'Looking for a pipette for volume {volume}')

        pipettes = []
        minVolStr = ''
        for mount,pipette in self.protocol.loaded_instruments.items():
            if volume>pipette.min_volume:
                pipettes.append({'object':pipette})
    

        for pipette in pipettes:
            max_volume = pipette['object'].max_volume
            ntransfers = ceil(volume/max_volume)
            vol_per_transfer = volume / ntransfers
            
            pipette['ntransfers'] = ntransfers

            # **Peter** personally apologizes for these impressively long lines,
            # which he believes to be correct.  The systematic error is added
            # straight (i.e, not sumsq) while the random is added as sumsq,
            # then the two are combined as sumsq 
            pipette['uncertainty'] = sqrt(
                (ntransfers*self._pipette_uncertainty(max_volume,vol_per_transfer,'random')**2)+
                (ntransfers*self._pipette_uncertainty(max_volume,vol_per_transfer,'systematic'))**2
            )

            # last_transfer_vol_maxmin = volume - max_volume*(ntransfers-1)
            # pipette['total_uncertainty_maxmin'] = sqrt(
            #     (ntransfers-1*_pipette_uncertainty(max_volume,max_volume,'random')**2+ 
            #     _pipette_uncertainty(max_volume,last_transfer_vol_maxmin,'random')**2)+
            #     ((ntransfers-1)*_pipette_uncertainty(max_volume,vol_per_transfer,'systematic')+
            #     _pipette_uncertainty(max_volume,last_transfer_vol_maxmin,'systematic')**2)
            #     )


        self._app.logger.debug(f'Found pipettes with suitable minimum volume and computed uncertainties: {pipettes}')
        if not pipettes:
            raise ValueError('No suitable pipettes found!\\n')
        
        if(method == 'uncertainty'):
            pipette = min(pipettes,key=lambda x: x['uncertainty'])
        elif(method == 'min_transfers'):
            min_xfers = min(pipettes,key=lambda x: x['ntransfers'])['ntransfers']
            acceptable_pipettes = filter(lambda x: x['ntransfers']==min_xfers,pipettes)
            pipette = min(acceptable_pipettes,key=lambda x: x['object'].max_volume) 
        else:
            raise ValueError(f'Pipette selection method {method} was not recognized.')
        self._app.logger.debug(f'Chosen pipette: {pipette}')
        return pipette['object']

    def _pipette_uncertainty(self,maxvolume,volume,errortype):
        '''pipet uncertainties from the opentrons gen 1 whitepaper 
        @ https://opentrons.com/publications/OT-2-Pipette-White-Paper-GEN1.pdf
        
        pipette          moving uL      random error uL ±     systematic error uL ±
        P10 single          10                  0.1                 0.2
        P10 single          5                   0.15                0.25
        P10 single          1                   0.05                0.15

        P50 single          50                  0.2                 0.5
        P50 single          25                  0.15                0.375
        P50 single          5                   0.25                0.25

        P300 single         300                 0.9                 1.8
        P300 single         150                 0.6                 1.5
        P300 single         30                  0.45                0.9

        P1000 single        1000                1.5                 7
        P1000 single        500                 1.0                 5
        P1000 single        100                 1.0                 2
        '''
        #dict of uncertainty data where params are  error = a * volume + b
        pipette_uncertainties = [
        {'size':10,  'gen':1,'random_a':0.00491803278688525,  'random_b':0.0737704918032787,'systematic_a':0.00491803278688525,'systematic_b':0.173770491803279},
        {'size':50,  'gen':1,'random_a':-0.000983606557377049,'random_b':0.226229508196721, 'systematic_a':0.0055327868852459, 'systematic_b':0.227459016393443},
        {'size':300, 'gen':1,'random_a':0.00168032786885246,  'random_b':0.381147540983607, 'systematic_a':0.00327868852459016,'systematic_b':0.875409836065574},
        {'size':1000,'gen':1,'random_a':0.000573770491803279, 'random_b':0.860655737704918, 'systematic_a':0.00549180327868852,'systematic_b':1.73770491803279}
        ]

        for pu in pipette_uncertainties:
            if pu['size'] == maxvolume:
                #I think sum squares is the correct way to combine these errors, but not 100%
                if errortype == 'random':
                    return pu['random_a'] * volume + pu['random_b']
                elif errortype == 'systematic':
                    return pu['systematic_a'] * volume + pu['systematic_b']
                else:
                    return None


   
