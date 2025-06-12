import numpy
import time
import logging
from AFL.automation.APIServer.Driver import Driver


class Dummy_OT2_Driver(Driver):
    defaults={}
    defaults['execute_delay']=1
    def __init__(self,overrides=None):
        self.app = None
        Driver.__init__(self,name='Dummy_OT2_Driver',defaults=self.gather_defaults(),overrides=overrides)
        self.reset_prep_targets()

    def reset_prep_targets(self):
        self.prep_targets = []

    def add_prep_targets(self,targets,reset=False):
        if reset:
            self.reset_prep_targets()
        self.prep_targets.extend(targets)

    def get_prep_target(self):
        return self.prep_targets.pop(0)

    def status(self):
        status = []
        if len(self.prep_targets)>0:
                status.append(f'Next prep target: {self.prep_targets[0]}')
                status.append(f'Remaining prep targets: {len(self.prep_targets)}')
        else:
                status.append('No prep targets loaded')
        return status

    @Driver.quickbar(qb={'button_text':'Refill Tipracks',
        'params':{
        'mount':{'label':'Which Pipet left/right/both','type':'text','default':'both'},
        }})
    def reset_tipracks(self,mount='both'):
        logging.info('Called reset tipracks')
                

    @Driver.quickbar(qb={'button_text':'Home',
        })
    def home(self,**kwargs):
        logging.info('Homing robot')

    def parse_well(self,loc):
        for i,loc_part in enumerate(list(loc)):
            if loc_part.isalpha():
                break
        slot = loc[:i]
        well = loc[i:]
        return slot,well

    def get_wells(self,locs):
        self.app.logger.debug(f'Converting locations to well objects: {locs}')
        wells = []
        for loc in listify(locs):
            slot,well = self.parse_well(loc)
            labware = self.get_labware(slot)
            wells.append(labware[well])
        self.app.logger.debug(f'Created well objects: {wells}')
        return wells

    def get_labware(self,slot):
        logging.info(f'Getting labware from slot {slot}')

    def load_labware(self,name,slot,module=None,**kwargs):
        logging.info(f'Loading labware {name} into slot {slot}')
        
    def set_temp(self,slot,temp):
        '''Set the temperature of a tempdeck in slot slot'''
        logging.info(f'Called set_temp with slot={slot} and temp={temp}')
    
    def get_temp(self,slot):
        '''Get the temperature of a tempdeck in slot slot'''
        logging.info(f'Called get_temp with slot={slot}')

    def deactivate_temp(self,slot):
        '''Disablea tempdeck in slot slot'''
        logging.info('Called deactivate_temp')

    def set_shake(self,rpm):
        logging.info(f'Called set_shake with rpm={rpm}')

    def stop_shake(self):
        logging.info('Called stop_shake')

    def set_shaker_temp(self,temp):
        logging.info(f'Called set_shaker_temp with temp={temp}')

    def unlatch_shaker(self):
        logging.info('Called latch_shaker')

    def latch_shaker(self):
        logging.info('Called latch_shaker')

    def get_shaker_temp(self):
        logging.info('Called get_shake_temp')

    def get_shake_rpm(self):
        logging.info('Called get_shake_rpm')

    def get_shake_latch_status(self):
        logging.info('Called get_shake_latch_status')

    def load_instrument(self,name,mount,tip_rack_slots,**kwargs):
        logging.info(f'Loading instrument {name} into {mount} with tip_racks={tip_rack_slots}')

    @Driver.quickbar(qb={'button_text':'Transfer',
        'params':{
        'source':{'label':'Source Well','type':'text','default':'1A1'},
        'dest':{'label':'Dest Well','type':'text','default':'1A1'},
        'volume':{'label':'Volume (uL)','type':'float','default':300}
        }})
    def transfer(self,source,dest,volume,*args,**kwargs):
        logging.info(f'Transferring {volume} uL from {source} to {dest} with kwargs: {kwargs}')
    

    def set_aspirate_rate(self,rate=150):
        logging.info(f'Setting aspirate rate to {rate}')

    def set_dispense_rate(self,rate=300):
        logging.info(f'Setting dispense rate to {rate}')

    def set_gantry_speed(self,speed=400):
        logging.info(f'Setting gantry speed to {speed}')

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *

