from AFL.automation.loading.SampleCell import SampleCell
from AFL.automation.APIServer.Driver import Driver
from collections import defaultdict
import warnings
import time

import numpy as np

import math

class PneumaticPressureSampleCell(Driver,SampleCell):
    '''
        Class for a sample cell consisting of a push-through, pneumatically-closed sample loader.

        Driven by a variable-pressure regulator.

    '''
    defaults={}
    defaults['load_pressure'] = 2
    defaults['blowout_pressure'] = 20

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
    defaults['external_load_complete_trigger'] = False


    def __init__(self,pctrl,
                      relayboard,
                      digitalin=None,
                      rinse1_tank_level=950,
                      rinse2_tank_level=950,
                      waste_tank_level=0,
                      load_stopper=None,
                      overrides=None, 
                      ):
        '''
            pctrl: a pressurecontroller object supporting the set_P method() and the optional p_ramp() method.
                e.g. pctrl = DigitalOutPressureController(LabJackDigitalOut(...))

            relayboard: a relay board object supporting string-based setChannels() method
                required channels are 'arm-up','arm-down',
                'rinse1','rinse2','blow','enable','piston-vent','postsample'
                e.g. selector = SainSmartRelay(port,portlabels={'catch':1,'cell':2,'rinse':3,'waste':4,'air':5})

        '''
        self._app = None
        Driver.__init__(self,name='PneumaticSampleCell',defaults=self.gather_defaults(),overrides=overrides)
        self.pctrl = pctrl
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
        self.state = 'READY'
        self.rinse_status = 'Not Rinsing'
        
        if load_stopper is not None:
            if type(load_stopper) is not list:
                load_stopper = [load_stopper]  
            self.load_stopper=load_stopper
            # remove any load clients and push this object in for direct control
            for ls in load_stopper:
                self.load_stopper.load_client = None
                self.load_stopper.load_object = self
                self.load_stopper.reset()  # initialize and start load stopping threads
        else:
            self.load_stopper = None

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
            self.pctrl.app = app
            self.relayboard.app = app
            for ls in self.load_stopper:
                ls.app = app
            
    @property
    def data(self):
        return self._data

    @app.setter
    def data(self,data):
        if data is None:
            self._data = data
        else:
            self._data = data
            self.pctrl.data = data
            self.relayboard.data = data
            for ls in self.load_stopper:
                ls.data = data
            
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

        if self.load_stopper is not None:
            for ls in self.load_stopper:
                status.extend(self.load_stopper.status())
            
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
    def loadSample(self,cellname='cell',sampleVolume=None):
        '''
        Load a sample into the cell
        
        Params `cellname` and `sampleVolume` are kept for backward compat, but are deprecated and unused.
        '''
        
        if self.state != 'READY':
            raise Exception('Tried to load sample but cell not READY.')
        self.state = 'PREPARING TO LOAD'
        self.relayboard.setChannels({'piston-vent':True,'postsample':False})
        self._arm_down()
        time.sleep(self.config['vent_delay'])
        self.relayboard.setChannels({'piston-vent':False,'postsample':True})
        print('setting state...')
        self.state = 'LOAD IN PROGRESS'
        print('sending dispense command')
        self.pctrl.timed_dispense(self.config['load_pressure'],self.config['load_timeout'],block=False)
        
        while(self.pctrl.dispenseRunning() and not self.loadStoppedExternally):
            print(f'awaiting pump complete, {self.pump.getStatus()}')
            time.sleep(0.02)
            
        
        self.loadStoppedExternally = False
        self.relayboard.setChannels({'postsample':False})
        self.state = 'LOADED'
    @Driver.quickbar(qb={'button_text':'Load Sample',
        'params':{'sampleVolume':{'label':'Sample Volume (mL)','type':'float','default':0.3}}})
    def advanceSample(self,active_sensor_ids=None):
        '''
        Move a sample from one measurement cell to the next
        
        Params:
            active_sensor_ids (list or NoneType): if provided, a list of sensor id's to be left enabled for this measurement.
                all other sensor id's will not be able to stop the load.
        '''
        
        if self.state != 'LOADED':
            raise Exception('Tried to advance sample but no sample is loaded.')
        self.state = 'PREPARING TO Advance'
        self.relayboard.setChannels({'postsample':True})
        print('setting state...')
        self.state = 'LOAD IN PROGRESS'
        print('sending dispense command')
        self.pctrl.timed_dispense(self.config['load_pressure'],self.config['load_timeout'],block=False)
        
        while(self.pctrl.dispenseRunning() and not self.loadStoppedExternally):
            print(f'awaiting pump complete, {self.pump.getStatus()}')
            time.sleep(0.02)
            
        
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
                    self.pctrl.stop()
                    self.relayboard.setChannels({'postsample':False})
                    self.loadStoppedExternally=True
                    if self.data is not None:
                        self.data['load_stop_source'] = 'external'
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

        for i,(step,waittime) in enumerate(self.config['rinse_program']):
            self.rinse_status = f'Rinse Program Step {i}/{len(self.config["rinse_program"])}: {step} for {waittime}s'
            if step is not None:
                if step is 'blow':
                    self.pctrl.set_P(self.config['blowout_pressure'])
                else:
                    self.relayboard.setChannels({step:True})
            time.sleep(waittime)
            if step is not None:
                if step is 'blow':
                    self.pctrl.set_P(0)
                else:
                    self.relayboard.setChannels({step:False})
        self.relayboard.setChannels({'postsample':False})
        self._arm_up()
        self.state = 'READY'
        self.rinse_status = 'Not Rinsing'
    
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
        
    @Driver.unqueued()
    @Driver.quickbar(qb={'button_text':'calibrate', 'params':{}})
    def calibrate_sensor(self):
        if self.load_stopper is not None:
            out = []
            for ls in self.load_stopper:
                out.append(ls.sensor.calibrate())
            return out

    @Driver.unqueued()
    def read_sensor(self):
        if self.load_stopper is not None:
            out = []
            for ls in self.load_stopper:
                out.append(ls.sensor.read())
            return out

    @Driver.unqueued(render_hint='1d_plot',xlin=True,ylin=True,xlabel='time',ylabel='Signal (V)')
    def read_sensor_poll(self,**kwargs):
        if self.load_stopper is not None:
            out = []
            for ls in self.load_stopper:
                output = np.transpose(ls.poll.read())
                print('Serving sensor poll:',len(output),len(output[0]),len(output[1]))
                out.append(list(output))
            return out

    @Driver.unqueued(render_hint='1d_plot',xlin=True,ylin=True,xlabel='time',ylabel='Signal (V)')
    def read_sensor_poll_load(self,**kwargs):
        if self.load_stopper is not None:
            out = []
            for ls in self.load_stopper:
                out.append(list(np.transpose(ls.poll.read_load_buffer()))
        return out
    
    def set_sensor_config(self,**kwargs):
        if self.load_stopper is not None:
            if sensor_n in **kwargs:
                self.load_stopper[kwargs[sensor_n]].update(kwargs)
                self.load_stopper[kwargs[sensor_n]].reset()                        
            else: # assume it should apply to all
                for ls in self.load_stopper:
                    ls.config.update(kwargs)
                    ls.reset()

    def get_sensor_config(self,**kwargs):
        if self.load_stopper is not None:
            out = []
            for ls in self.load_stopper:
                out.append(ls.config)
            return out

    @Driver.unqueued()
    @Driver.quickbar(qb={'button_text':'Reset Sensor', 'params':{}})
    def sensor_reset(self,sensor_n = None):
        if self.load_stopper is not None:
            if sensor_n is not None:
                self.load_stopper[sensor_n].reset_poll()
                self.load_stopper[sensor_n].reset_stopper()
                if self.load_stopper[sensor_n]._app is not None:
                    self.load_stopper[sensor_n].poll.app = self._app
                    self.load_stopper[sensor_n].stopper.app = self._app
                if self.load_stopper[sensor_n]._data is not None:
                    self.load_stopper[sensor_n].poll.data = self._data
                    self.load_stopper[sensor_n].stopper.data = self._data
                self.load_stopper[sensor_n].poll.start()
                self.load_stopper[sensor_n].stopper.start()
            else:
                for ls in self.load_stopper:
                    ls.reset_poll()
                    ls.reset_stopper()
                    if ls_app is not None:
                        ls.poll.app = self._app
                        ls.stopper.app = self._app
                    if ls._data is not None:
                        ls.poll.data = self._data
                        ls.stopper.data = self._data
                    ls.poll.start()
                    ls.stopper.start()
