from NistoRoboto.loading.SampleCell import SampleCell
from NistoRoboto.APIServer.driver.Driver import Driver
from collections import defaultdict
import warnings
import time

import math

class PneumaticSampleCell(Driver,SampleCell):
    '''
        Class for a sample cell consisting of a push-through, pneumatically-closed sample loader.

        Driven by a syringe pump.

    '''
    defaults={}
    defaults['load_speed'] = 2
    defaults['air_speed'] = 30
    defaults['withdraw_vol'] = 1.5
    defaults['large_dispense_vol'] = 5

    defaults['arm_move_delay'] = 0.2
    defaults['rinse_program'] = [
                                ('rinse1',5),
                                (None,2),
                                ('rinse2',5),
                                ('blow',5),
                                (None,0.5),
                                ('blow',5)
                                ] 
    defaults['catch_to_cell_vol'] = 1.15
    defaults['external_load_complete_trigger'] = False


    def __init__(self,pump,
                      relayboard,
                      rinse1_tank_level=950,
                      rinse2_tank_level=950,
                      waste_tank_level=0,
                      overrides=None, 
                      ):
        '''
            pump: a pump object supporting withdraw() and dispense() methods
                e.g. pump = NE1KSyringePump(port,syringe_id_mm,syringe_volume)

            relayboard: a relay board object supporting string-based setChannels() method
                required channels are 'arm-up','arm-down',
                'rinse1','rinse2','blow','enable','piston-vent','postsample'
                e.g. selector = SainSmartRelay(port,portlabels={'catch':1,'cell':2,'rinse':3,'waste':4,'air':5})

        '''
        self._app = None
        Driver.__init__(self,name='PneumaticSampleCell',defaults=self.gather_defaults(),overrides=overrides)
        self.pump = pump
        self.relayboard = relayboard
        self.cell_state = defaultdict(lambda: 'clean')

        self.rinse1_tank_level = rinse1_tank_level
        self.waste_tank_level = waste_tank_level
        self.rinse2_tank_level = rinse2_tank_level

        self.relayboard.setChannels({'enable':True,'piston-vent':True})
        self._arm_up()
        time.sleep(0.2)
        self.pump.setRate(self.config['air_speed'])
        self.pump.dispense(self.config['large_dispense_vol'])
        self.pump.withdraw(self.config['withdraw_vol'])
        self.state = 'READY'
        


    def reset_tank_levels(self,rinse1=950,rinse2=950,waste=0):
        self.rinse1_tank_level = rinse1
        self.waste_tank_level = waste
        self.rinse2_tank_level = rinse2

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self,app):
        if app is None:
            self._app = app
        else:
            self._app = app
            self.pump.app = app
            self.relayboard.app = app

    def status(self):
        status = []
        status.append(f'State: {self.state}')
        status.append(f'Rinse 1 tank: {self.rinse1_tank_level} mL')
        status.append(f'Rinse 2 tank: {self.rinse2_tank_level} mL')
        status.append(f'Waste tank: {self.waste_tank_level} mL')
        status.append(f'Relay status: {self.relayboard.getChannels()}')
        return status
    
    def _arm_up(self):
        self.relayboard.setChannels({'piston-vent':True,'arm-up':True,'arm-down':False})
        time.sleep(self.config['arm_move_delay'])
        #when equipped with limit switch, add limit switch logic here
        self.arm_state = 'UP'

    def _arm_down(self):
        self.relayboard.setChannels({'piston-vent':True,'arm-up':False,'arm-down':True})
        time.sleep(self.config['arm_move_delay'])
        #when equipped with limit switch, add limit switch logic here
        self.arm_state = 'DOWN'

    def loadSample(self,cellname='cell',sampleVolume=0):
        if self.state != 'READY':
            raise Exception('Tried to load sample but cell not READY.')
        self.state = 'PREPARING TO LOAD'
        self._arm_down()
        self.relayboard.setChannels({'piston-vent':False,'postsample':True})
        self.pump.setRate(self.config['load_speed'])
        self.state = 'LOAD IN PROGRESS'
        self.pump.dispense(self.config['catch_to_cell_vol'])
        self.relayboard.setChannels({'postsample':False})
        self.state = 'LOADED'

    @Driver.unqueued(render_hint='raw')
    def stopLoad(self,**kwargs):
        try:
            if kwargs['secret'] == 'xrays>neutrons':
                if self.state!= 'LOAD IN PROGRESS':
                    warnings.warn('Tried to stop load but load is not in progress. Doing nothing.',stacklevel=2)
                    return 'There is no load running.'
                else:
                    self.pump.stop()
                    self.relayboard.setChannels({'postsample':False})
                    return 'Load stopped successfully.'
            else:
                return 'Wrong secret.'
        except KeyError:
            return 'Need valid secret to stop load.'
     
    def rinseCell(self,cellname='cell'):
        if self.state != 'LOADED':
            if self.state == 'READY':
                warnings.warn('Rinsing despite READY state.  This is OK, just a little extra.  Lowering the arm to rinse.',stacklevel=2)
                self._arm_down()
            else:
                raise Exception(f'Cell in inconsistent state: {self.state}')
        self.relayboard.setChannels({'piston-vent':False,'postsample':True})



        for step,waittime in self.config['rinse_program']:
            if step is not None:
                self.relayboard.setChannels({step:True})
            time.sleep(waittime)
            if step is not None:
                self.relayboard.setChannels({step:False})
        self.relayboard.setChannels({'postsample':False})
        self._arm_up()
        self.pump.setRate(self.config['air_speed'])
        self.pump.dispense(self.config['large_dispense_vol'])
        self.pump.withdraw(self.config['withdraw_vol'])

        self.state = 'READY'
    
    def rinseAll(self):
        self.rinseCell()

    def setRinseLevel(self,vol):
        self.rinse_tank_level = vol

    def setWasteLevel(self,vol):
        self.waste_tank_level = vol
