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
    defaults['vent_delay'] = 0.5
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
                      digitalin=None,
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
        self.digitalin = digitalin

        self.rinse1_tank_level = rinse1_tank_level
        self.waste_tank_level = waste_tank_level
        self.rinse2_tank_level = rinse2_tank_level

        self.loadStoppedExternally = False
        self.state = 'FRESH'
        if 'enable' in self.relayboard.labels.keys():
            self.relayboard.setChannels({'enable':True})
        
        self._USE_ARM_LIMITS = False
        self._USE_DOOR_INTERLOCK = False
        if self.digitalin is not None:
            if 'ARM_UP' in self.digitalin.state.keys() and 'ARM_DOWN' in self.digitalin.state.keys():
                self._USE_ARM_LIMITS =True
            if 'DOOR' in self.digitalin.state.keys():
                self._USE_DOOR_INTERLOCK = True



        self.relayboard.setChannels({'piston-vent':True})
        self._arm_up()
        time.sleep(0.2)
        self.pump.setRate(self.config['air_speed'])
        # self.pump.dispense(self.config['large_dispense_vol'])
        # self.pump.withdraw(self.config['withdraw_vol'])
        self.reset_pump(dispense=False)
        self.state = 'READY'
        self.rinse_status = 'Not Rinsing'

    @Driver.quickbar(qb={'button_text':'Reset Pump',
        'params':{
            'dispense':{'label':'dispense','type':'bool','default':False}
        }})
    def reset_pump(self,dispense=False):
        self.pump.setRate(self.config['air_speed'])
        if dispense and (self.pump_level>0):
            self.pump.dispense(self.pump_level)
        self.pump.withdraw(self.config['withdraw_vol'])
        self.pump_level = self.config['withdraw_vol']

    @Driver.quickbar(qb={'button_text':'Reset Tank Levels',
        'params':{
        'rinse1':{'label':'Rinse1 (mL)','type':'float','default':950},
        'rinse2':{'label':'Rinse2 (mL)','type':'float','default':950},
        'waste':{'label':'Waste (mL)','type':'float','default':0}
        }})
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
        status.append(f'Arm State: {self.arm_state}')
        status.append(f'Rinse 1 tank: {self.rinse1_tank_level} mL')
        status.append(f'Rinse 2 tank: {self.rinse2_tank_level} mL')
        status.append(f'Waste tank: {self.waste_tank_level} mL')
        status.append(f'Relay status: {self.relayboard.getChannels()}')
        if self._USE_ARM_LIMITS:
            status.append(f"Arm Up Limit: {not self.digitalin.state['ARM_UP']} / Arm Down Limit{not self.digitalin.state['ARM_DOWN']}")
        if self._USE_DOOR_INTERLOCK:
            status.append(f"Door closed: {not self.digitalin.state['DOOR']}")
        if self.digitalin is not None:
            status.append(f'DIO state: {self.digitalin.state}') 
        status.append(f'Pump Level: {self.pump_level} mL')
        status.append(self.rinse_status)
            
        return status
 
    def _arm_interlock_check(self):
        if self._USE_DOOR_INTERLOCK:
            oldstate = self.state
            while self.digitalin.state['DOOR']:
                time.sleep(0.2)
                self.state = 'AWAITING DOOR CLOSED BEFORE MOVING ARM'
            self.state = oldstate

    def _arm_up(self):
        self._arm_interlock_check()
        self.relayboard.setChannels({'piston-vent':True,'arm-up':True,'arm-down':False})
        if self._USE_ARM_LIMITS:
            while self.digitalin.state['ARM_UP']:
                time.sleep(0.1)
        else:
            time.sleep(self.config['arm_move_delay'])
        self.arm_state = 'UP'

    def _arm_down(self):
        self._arm_interlock_check()
        self.relayboard.setChannels({'piston-vent':True,'arm-up':False,'arm-down':True})
        time.sleep(self.config['arm_move_delay'])
        if self._USE_ARM_LIMITS:
            while self.digitalin.state['ARM_DOWN']:
                time.sleep(0.1)
        else:
            time.sleep(self.config['arm_move_delay'])
        self.arm_state = 'DOWN'

    @Driver.quickbar(qb={'button_text':'Load Sample',
        'params':{'sampleVolume':{'label':'Sample Volume (mL)','type':'float','default':0.3}}})
    def loadSample(self,cellname='cell',sampleVolume=0):
        if self.state != 'READY':
            raise Exception('Tried to load sample but cell not READY.')
        self.state = 'PREPARING TO LOAD'
        self.relayboard.setChannels({'piston-vent':True,'postsample':False})
        self._arm_down()
        time.sleep(self.config['vent_delay'])
        self.relayboard.setChannels({'piston-vent':False,'postsample':True})
        print('setting pump rate...')
        self.pump.setRate(self.config['load_speed'])
        print('setting state...')
        self.state = 'LOAD IN PROGRESS'
        print('sending dispense command')
        self.pump.dispense(self.config['catch_to_cell_vol']+sampleVolume/2,block=False)
        while(self.pump.getStatus()[0] != 'S' and not self.loadStoppedExternally):
            print(f'awaiting pump complete, {self.pump.getStatus()}')
            time.sleep(0.1)

        infusion_vol = self.pump.getStatus()[1]
        self.pump_level -= infusion_vol
        if self.pump_level<0:
            raise Exception(f'Pump level found to be less than zero: {self.pump_level}')

        self.loadStoppedExternally = False
        self.relayboard.setChannels({'postsample':False})
        self.state = 'LOADED'

    @Driver.unqueued(render_hint='raw')
    def stopLoad(self,**kwargs):
        print(kwargs)
        try:
            if kwargs['secret'] == 'xrays>neutrons':
                if self.state!= 'LOAD IN PROGRESS':
                    warnings.warn('Tried to stop load but load is not in progress. Doing nothing.',stacklevel=2)
                    return 'There is no load running.'
                else:
                    self.pump.stop()
                    self.relayboard.setChannels({'postsample':False})
                    self.loadStoppedExternally=True
                    return 'Load stopped successfully.'
            else:
                return 'Wrong secret.'
        except KeyError:
            return 'Need valid secret to stop load.'

    @Driver.quickbar(qb={'button_text':'Rinse Cell'})
    def rinseCell(self,cellname='cell'):
        if self.state != 'LOADED':
            if self.state == 'READY':
                warnings.warn('Rinsing despite READY state.  This is OK, just a little extra.  Lowering the arm to rinse.',stacklevel=2)
                self._arm_down()
            else:
                raise Exception(f'Cell in inconsistent state: {self.state}')
        self.relayboard.setChannels({'piston-vent':False,'postsample':True})


        # self.pump.setRate(self.config['air_speed'])
        # self.pump.dispense(self.config['large_dispense_vol'],block=False) # removed for OEM pump w/o force limiter

        self.rinse_status = 'Pushing with syringe...'
        #need to dispense with piston down, and then withdraw with piston up
        self.pump.setRate(self.config['air_speed'])
        if self.pump_level>0:
            self.pump.dispense(self.pump_level)

        for i,(step,waittime) in enumerate(self.config['rinse_program']):
            self.rinse_status = f'Rinse Program Step {i}/{len(self.config["rinse_program"])}: {step} for {waittime}s'
            if step is not None:
                self.relayboard.setChannels({step:True})
            time.sleep(waittime)
            if step is not None:
                self.relayboard.setChannels({step:False})
        self.relayboard.setChannels({'postsample':False})
        self._arm_up()
        self.state = 'READY'
        self.rinse_status = 'Not Rinsing'
        # self.pump.withdraw(self.config['withdraw_vol'],block=True)
        self.reset_pump(dispense=False)

    
    def rinseAll(self):
        self.rinseCell()

    def setRinseLevel(self,vol):
        self.rinse_tank_level = vol

    def setWasteLevel(self,vol):
        self.waste_tank_level = vol

    @Driver.quickbar(qb={'button_text':'Prime Rinse'})
    def primeRinse(self,waittime=10):
        if self.state != 'READY':
            raise Exception(f'Cell in inconsistent state: {self.state}')

        self._arm_up()

        self.relayboard.setChannels({'rinse1':True,'rinse2':False})
        time.sleep(waittime)
        self.relayboard.setChannels({'rinse1':False,'rinse2':True})
        time.sleep(waittime)
        self.relayboard.setChannels({'rinse1':False,'rinse2':False})

