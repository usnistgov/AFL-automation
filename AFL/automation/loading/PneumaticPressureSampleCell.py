import requests

from AFL.automation.loading.SampleCell import SampleCell
from AFL.automation.APIServer.Driver import Driver
from collections import defaultdict
import warnings
import time

import numpy as np

class PneumaticPressureSampleCell(Driver,SampleCell):
    '''
        Class for a sample cell consisting of a push-through, pneumatically-closed sample loader.

        Driven by a variable-pressure regulator.

    '''
    defaults={}
    defaults['load_mode'] = 'static'
    defaults['load_pressure'] = 2
    defaults['blowout_pressure'] = 20

    defaults['load_timeout'] = 60
    
    defaults['arm_move_delay'] = 0.2
    defaults['arm_move_timeout'] = 10
    defaults['vent_delay'] = 0.5
    defaults['rinse_program'] = [
                                ('rinse1',5),
                                (None,2),
                                ('rinse2',5),
                                ('blow',5),
                                (None,0.5),
                                ('blow',5)
                                ] 
    defaults['external_load_complete_trigger'] = False  # Currently unused.
    defaults['ramp_load_stop_pressure'] = 7
    defaults['ramp_load_duration'] = 20
    defaults['enforce_door_closed'] = True

    def __init__(self,pctrl,
                      relayboard,
                      digitalin=None,
                      rinse1_tank_level=950,
                      rinse2_tank_level=950,
                      waste_tank_level=0,
                      load_stopper=None,
                      robot_interlock_host=None,
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
        if 'enable' in self.relayboard.labels.values():
            self.relayboard.setChannels({'enable':True})

        if robot_interlock_host:
            self.robot_interlock_url = f'http://{robot_interlock_host}:31950/robot/door/status'
        else:
            self.robot_interlock_url = None
        self._last_robot_door_state = None


        self._USE_ARM_LIMITS = False
        self._USE_DOOR_INTERLOCK = False
        if self.digitalin is not None:
            if 'ARM_UP' in self.digitalin.state.keys() and 'ARM_DOWN' in self.digitalin.state.keys():
                self._USE_ARM_LIMITS =True
            if 'DOOR' in self.digitalin.state.keys():
                self._USE_DOOR_INTERLOCK = True
        if self.robot_interlock_url:
            self._USE_DOOR_INTERLOCK = True




        self.relayboard.setChannels({'piston-vent':True})
        self._arm_up()
        time.sleep(0.2)
        self.log_info("Successfully initialized PneumaticPressureSampleCell.")

        self.state = 'READY'
        self.rinse_status = 'Not Rinsing'
        
        if load_stopper is not None:
            if type(load_stopper) is not list:
                load_stopper = [load_stopper]  
            self.load_stopper=load_stopper
            # remove any load clients and push this object in for direct control
            for ls in load_stopper:
                ls.load_client = None
                ls.load_object = self
                ls.reset()  # initialize and start load stopping threads
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

    @data.setter
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
            status.append(f"Arm Up Limit: {self.digitalin.state['ARM_UP']} / Arm Down Limit{self.digitalin.state['ARM_DOWN']}")
        if self._USE_DOOR_INTERLOCK:
            status.append(f"Door closed: {not self._door_state()}")
        if self.digitalin is not None:
            status.append(f'DIO state: {self.digitalin.state}') 
        status.append(self.rinse_status)

        if self.load_stopper is not None:
            for ls in self.load_stopper:
                status.extend(ls.status())
            
        return status

    def _arm_interlock_check(self):
        if self._USE_DOOR_INTERLOCK:
            if not self.config['enforce_door_closed']:
                self.log_warning('Door-closed interlock check is disabled; moving arm without verifying the door is closed.')
                return
            oldstate = self.state
            wait_started = None
            last_log_time = None
            startup_message = (
                ' Driver initialization is paused; the API server will not start '
                'until initialization completes.'
                if oldstate == 'FRESH' else ''
            )
            if self.digitalin is not None and 'DOOR' in self.digitalin.state:
                door_source = 'digital input DOOR'
            else:
                door_source = f'robot door status at {self.robot_interlock_url}'

            try:
                while self._door_state():
                    self.state = 'AWAITING DOOR CLOSED BEFORE MOVING ARM'
                    now = time.monotonic()
                    if wait_started is None:
                        wait_started = now
                    if last_log_time is None or now - last_log_time >= 5.0:
                        self.log_warning(
                            f'Arm motion blocked: door reports OPEN ({door_source}). '
                            f'Waiting for the door to close ({now - wait_started:.1f} s elapsed). '
                            'Close the door to continue; this wait has no timeout.'
                            + startup_message
                        )
                        last_log_time = now
                    time.sleep(0.2)
            except KeyboardInterrupt:
                self.log_warning(
                    'Door interlock wait interrupted; arm motion was not started.'
                    + (' Driver initialization did not complete; the API server '
                       'was not started.' if oldstate == 'FRESH' else '')
                )
                raise

            self.state = oldstate
            if wait_started is not None:
                # Before API logging is configured, warning messages remain
                # visible through Python logging's fallback stderr handler.
                log = self.log_warning if self.app is None else self.log_info
                log(
                    f'Door reports CLOSED ({door_source}) after '
                    f'{time.monotonic() - wait_started:.1f} s; resuming arm motion.'
                )

    def _door_state(self):
        if self.digitalin is not None:
            if 'DOOR' in self.digitalin.state.keys():
                return not self.digitalin.state['DOOR']
        if self.robot_interlock_url is not None:
            state = requests.get(
                self.robot_interlock_url,
            headers = {'Opentrons-Version': '2'}).json()['data']['status']

            if state != self._last_robot_door_state:
                self.log_debug(f'Robot door status at {self.robot_interlock_url}: {state}')
                self._last_robot_door_state = state

            if state == 'open':
                return True
            elif state == 'closed':
                return False

    def _arm_up(self):
        # Before APIServer configures its handlers, logging's fallback handler
        # only displays WARNING and above. Keep startup progress visible there.
        log_progress = self.log_warning if self.app is None else self.log_info
        startup_message = (
            ' Driver initialization is paused; the API server will not start '
            'until initialization completes.'
            if self.state == 'FRESH' else ''
        )
        self._arm_interlock_check()
        log_progress(
            'Commanding arm UP: piston-vent=ON, arm-up=ON, arm-down=OFF. '
            'Waiting for the relay command to complete.' + startup_message
        )
        self.relayboard.setChannels({'piston-vent':True,'arm-up':True,'arm-down':False})
        log_progress('Arm UP relay command completed; checking the arm position.')
        if self._USE_ARM_LIMITS:
            pin = getattr(self.digitalin, 'ids', {}).get('ARM_UP')
            source = 'ARM_UP' if pin is None else f'ARM_UP (GPIO {pin})'
            wait_started = time.monotonic()
            last_log_time = None
            try:
                while self.digitalin.state['ARM_UP']:
                    now = time.monotonic()
                    if last_log_time is None or now - last_log_time >= 5.0:
                        input_states = self.digitalin.state.copy()
                        inputs = ', '.join(
                            f'{name}={int(bool(input_states[name]))} '
                            f'({"HIGH" if input_states[name] else "LOW"})'
                            for name in ('ARM_UP', 'ARM_DOWN')
                            if name in input_states
                        )
                        log_progress(
                            f'Waiting for arm UP limit switch {source} to become LOW (0). '
                            f'Inputs: {inputs}. Elapsed: {now - wait_started:.1f} s. '
                            'This wait has no timeout.' + startup_message
                        )
                        last_log_time = now
                    time.sleep(0.1)
            except KeyboardInterrupt:
                self.log_warning(
                    f'Arm UP limit-switch wait interrupted after '
                    f'{time.monotonic() - wait_started:.1f} s while waiting '
                    f'for {source} to become LOW (0).' + startup_message
                )
                raise
            log_progress(
                f'Arm UP limit switch {source} is LOW (0); arm position confirmed '
                f'after {time.monotonic() - wait_started:.1f} s.'
            )
        else:
            log_progress(
                'No arm-position limit inputs configured; waiting '
                f'{self.config["arm_move_delay"]:g} s for arm_move_delay.'
            )
            time.sleep(self.config['arm_move_delay'])
            log_progress('Arm UP move delay complete.')
        self.arm_state = 'UP'

    def _wait_for_arm_limit(self, limit_name, direction):
        """Wait for an active-low arm limit switch, with a bounded timeout."""
        timeout = self.config['arm_move_timeout']
        if timeout <= 0:
            raise ValueError('arm_move_timeout must be greater than zero.')

        self.log_info(
            f'Waiting up to {timeout:g} s for arm to reach {direction} limit '
            f'({limit_name}); the limit input must become LOW (0).'
        )
        start_time = time.monotonic()
        last_log_time = None
        while self.digitalin.state[limit_name]:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                self.log_error(
                    f'Arm {direction} motion timed out after {elapsed:.1f} s; '
                    f'digital inputs={self.digitalin.state.copy()}.'
                )
                raise TimeoutError(
                    f'Arm did not reach the {direction} limit ({limit_name}) '
                    f'within {timeout:g} s; input remains high.'
                )
            if last_log_time is None or elapsed - last_log_time >= 5.0:
                self.log_info(
                    f'Waiting for arm {direction} limit: elapsed={elapsed:.1f} s, '
                    f'timeout={timeout:g} s, digital inputs={self.digitalin.state.copy()}.'
                )
                last_log_time = elapsed
            time.sleep(min(0.1, timeout - elapsed))
        self.log_info(
            f'Arm {direction} limit {limit_name} is LOW (0); position confirmed '
            f'after {time.monotonic() - start_time:.1f} s.'
        )

    def _arm_down(self):
        self.log_info('Preparing arm DOWN motion; checking the door interlock.')
        self._arm_interlock_check()
        self._set_channels_logged(
            {'piston-vent':True,'arm-up':False,'arm-down':True}, 'Arm DOWN'
        )
        self.log_info(f'Arm DOWN: waiting {self.config["arm_move_delay"]:g} s for arm_move_delay.')
        time.sleep(self.config['arm_move_delay'])
        if self._USE_ARM_LIMITS:
            self._wait_for_arm_limit('ARM_DOWN', 'down')
        else:
            self.log_info(
                'Arm DOWN: no position limit inputs configured; waiting another '
                f'{self.config["arm_move_delay"]:g} s. Position is not sensor-confirmed.'
            )
            time.sleep(self.config['arm_move_delay'])
        self.arm_state = 'DOWN'
        self.log_info('Arm DOWN motion complete; arm_state=DOWN.')

    def _log_flow_state(self, context):
        """Log relay readback and cached inputs without querying door HTTP or sensors."""
        self.log_info(
            f'{context}: state={self.state}, arm_state={getattr(self, "arm_state", "unknown")}; '
            'reading relay states.'
        )
        try:
            channels = self.relayboard.getChannels()
        except Exception as exc:
            # A diagnostic readback must not interrupt the hardware workflow.
            self.log_warning(f'{context}: relay readback unavailable: {type(exc).__name__}: {exc}')
        else:
            self.log_info(f'{context}: relay readback={channels}.')
        if self.digitalin is not None:
            try:
                inputs = self.digitalin.state.copy()
            except Exception as exc:
                self.log_warning(f'{context}: cached digital inputs unavailable: {type(exc).__name__}: {exc}')
            else:
                self.log_info(f'{context}: cached digital inputs={inputs}.')

    def _set_channels_logged(self, channels, context):
        requested = ', '.join(f'{name}={"ON" if value else "OFF"}' for name, value in channels.items())
        self.log_info(f'{context}: commanding relays {requested}; waiting for command completion.')
        started = time.monotonic()
        self.relayboard.setChannels(channels)
        self.log_info(f'{context}: relay command completed in {time.monotonic() - started:.3f} s.')
        self._log_flow_state(context)

    @Driver.quickbar(qb={'button_text':'Load Sample',
        'params':{'sampleVolume':{'label':'Sample Volume (mL)','type':'float','default':0.3}}})
    def loadSample(self,cellname='cell',sampleVolume=None,load_dest_label=''):
        '''
        Load a sample into the cell
        
        Params `cellname` and `sampleVolume` are kept for backward compat, but are deprecated and unused.
        '''
        
        self.log_info(f'loadSample requested: state={self.state}, destination={load_dest_label!r}.')
        if self.state != 'READY':
            self.log_error(f'loadSample rejected: expected READY, current state={self.state}.')
            raise Exception('Tried to load sample but cell not READY.')
        started = time.monotonic()
        phase = 'reading load configuration'
        try:
            self.log_info(
                f'loadSample configuration: mode={self.config["load_mode"]}, '
                f'load_pressure={self.config["load_pressure"]} (controller pressure units), '
                f'load_timeout={self.config["load_timeout"]} s, vent_delay={self.config["vent_delay"]} s. '
                'Pressure drives loading; the blow relay is not activated. '
                'cellname and sampleVolume are unused.'
            )
            self._log_flow_state('loadSample starting')
            self.state = 'PREPARING TO LOAD'
            phase = 'venting before arm motion'
            self._set_channels_logged({'piston-vent':True,'postsample':False}, 'loadSample preparation')
            phase = 'lowering arm'
            self._arm_down()
            phase = 'waiting for vent delay'
            self.log_info(f'loadSample: arm DOWN; venting for {self.config["vent_delay"]:g} s.')
            time.sleep(self.config['vent_delay'])
            phase = 'closing vent and opening postsample'
            self._set_channels_logged({'piston-vent':False,'postsample':True}, 'loadSample flow path')
            self.loadStoppedExternally = False
            if load_dest_label == '':
                self.state = 'LOAD IN PROGRESS'
            else:
                self.state = f'LOAD IN PROGRESS to {load_dest_label}'
            phase = 'starting pressure dispense'
            dispense_started = time.monotonic()
            if self.config['load_mode'] == 'static':
                self.log_info(
                    f'loadSample: starting static dispense at pressure={self.config["load_pressure"]} '
                    f'for up to {self.config["load_timeout"]} s; state={self.state}.'
                )
                self.pctrl.timed_dispense(self.config['load_pressure'],self.config['load_timeout'],block=False)
            elif self.config['load_mode'] == 'ramp':
                self.log_info(
                    f'loadSample: starting ramp from pressure={self.config["load_pressure"]} '
                    f'to {self.config["ramp_load_stop_pressure"]} over {self.config["ramp_load_duration"]} s, '
                    f'then holding for {self.config["load_timeout"] - self.config["ramp_load_duration"]} s; '
                    f'state={self.state}.'
                )
                self.pctrl.ramp_dispense(self.config['load_pressure'],self.config['ramp_load_stop_pressure'],self.config['load_timeout'],const_time = self.config['load_timeout']-self.config['ramp_load_duration'])
            else:
                raise ValueError('invalid load_mode in config.  cannot load.  valid values are "static" or "ramp"')
            self.log_info('loadSample: pressure dispense call returned; waiting for controller completion or external stop.')
            phase = 'waiting for pressure dispense'
            last_log_time = None
            while(self.pctrl.dispenseRunning() and not self.loadStoppedExternally):
                elapsed = time.monotonic() - dispense_started
                if last_log_time is None or elapsed - last_log_time >= 5.0:
                    self.log_info(
                        f'loadSample progress: elapsed={elapsed:.1f} s, '
                        f'configured duration={self.config["load_timeout"]} s, '
                        f'state={self.state}, arm_state={self.arm_state}, external_stop=False. '
                        'Controller is running; liquid movement is not measured here.'
                    )
                    last_log_time = elapsed
                time.sleep(0.02)
            elapsed = time.monotonic() - dispense_started
            if self.loadStoppedExternally:
                reason = 'external stop received (sensor or stopLoad request)'
            elif elapsed >= self.config['load_timeout']:
                reason = 'configured dispense duration elapsed'
            else:
                reason = 'pressure controller is no longer running'
            self.log_info(f'loadSample: dispense ended after {elapsed:.1f} s; reason={reason}.')
            self.loadStoppedExternally = False
            phase = 'closing postsample after dispense'
            self._set_channels_logged({'postsample':False}, 'loadSample finish')
            self.state = 'LOADED'
            self.log_info(
                'loadSample: state=LOADED; this records dispense completion and does not verify liquid arrival. '
                'Waiting 1 s for sensor metadata.'
            )
            phase = 'waiting for sensor metadata'
            time.sleep(1) # crude hack to allow sensor to push data into packet
            self._log_flow_state('loadSample completed')
            self.log_info(f'loadSample completed in {time.monotonic() - started:.1f} s.')
        except (Exception, KeyboardInterrupt) as exc:
            self.log_error(
                f'loadSample failed during {phase} after {time.monotonic() - started:.1f} s; '
                f'state={self.state}, arm_state={getattr(self, "arm_state", "unknown")}: '
                f'{type(exc).__name__}: {exc}'
            )
            raise

    @Driver.quickbar(qb={'button_text':'Advance Sample',
        'params':{'sampleVolume':{'label':'Sample Volume (mL)','type':'float','default':0.3}}})
    def advanceSample(self,load_dest_label=''):
        '''
        Move a sample from one measurement cell to the next
        
        Params:
            load_dest_label (str, default ''): a 'destination label' for this load.  
                labeled sensors will only stop the load if their name is in this destination label.
                example: 
                    sensor 1 labeled 'afterSANS'
                    sensor 2 labeled 'beforeSPEC'
                    sensor 3 labeled '' (default)
                    
                    advanceSample(load_dest_label='afterSANS') --> sensor 1 or sensor 3 can stop it
                    advanceSample(load_dest_label='beforeSPEC afterSANS') --> sensor 1, sensor 2, or sensor 3 can stop it
                    advanceSample(load_dest_label='') --> only sensor 3 can stop it
        '''
        
        if self.state != 'LOADED':
            raise Exception('Tried to advance sample but no sample is loaded.')
        self.state = 'PREPARING TO Advance'
        self.relayboard.setChannels({'postsample':True})
        self.log_info('setting state...')
        if load_dest_label == '':
            self.state = 'LOAD IN PROGRESS'
        else:
            self.state = f'LOAD IN PROGRESS to {load_dest_label}'
        self.log_info('sending dispense command')
        self.pctrl.timed_dispense(self.config['load_pressure'],self.config['load_timeout'],block=False)
        self.loadStoppedExternally = False 
        while(self.pctrl.dispenseRunning() and not self.loadStoppedExternally):
            time.sleep(0.02)
            
        
        self.loadStoppedExternally = False
        self.relayboard.setChannels({'postsample':False})
        self.state = 'LOADED'
        time.sleep(1) # this is a crude hack to give the system time for the sensor data to push into the DataPacket
    
    @Driver.unqueued(render_hint='raw')
    def stopLoad(self,**kwargs):
        self.log_info(f'stopLoad requested: state={self.state}.')
        try:
            if kwargs['secret'] == 'xrays>neutrons':
                if 'LOAD IN PROGRESS' not in self.state:
                    self.log_warning(f'stopLoad ignored: no load is in progress; state={self.state}.')
                    warnings.warn('Tried to stop load but load is not in progress. Doing nothing.',stacklevel=2)
                    return 'There is no load running.'
                else:
                    self.log_info('stopLoad: stopping pressure controller; requesting pressure=0.')
                    self.pctrl.stop()
                    self.log_info('stopLoad: pressure controller stop command completed.')
                    self._set_channels_logged({'postsample':False}, 'stopLoad')
                    self.loadStoppedExternally=True
                    self.log_info('stopLoad: postsample OFF; external stop flag set for the loading workflow.')
                    if self.data is not None:
                        self.log_debug(self.data)
                        try:
                            self.data['load_stop_source'] = 'external'
                        except AttributeError:
                            pass
                    return 'Load stopped successfully.'
            else:
                self.log_warning('stopLoad rejected: incorrect stop secret.')
                return 'Wrong secret.'
        except KeyError:
            self.log_warning('stopLoad rejected: a valid stop secret is required.')
            return 'Need valid secret to stop load.'

    @Driver.quickbar(qb={'button_text':'Rinse Cell'})
    def rinseCell(self,cellname='cell'):
        self.log_info(f'rinseCell requested: state={self.state}, cellname={cellname!r}.')
        started = time.monotonic()
        phase = 'checking cell state'
        try:
            self._log_flow_state('rinseCell starting')
            if self.state != 'LOADED':
                if self.state == 'READY':
                    self.log_warning('rinseCell: cell is already READY; lowering the arm for an extra rinse.')
                    warnings.warn('Rinsing despite READY state.  This is OK, just a little extra.  Lowering the arm to rinse.',stacklevel=2)
                    phase = 'lowering arm'
                    self._arm_down()
                else:
                    raise Exception(f'Cell in inconsistent state: {self.state}')
            phase = 'closing vent and opening postsample'
            self._set_channels_logged({'piston-vent':False,'postsample':True}, 'rinseCell flow path')
            self.log_info(
                f'rinseCell program: {len(self.config["rinse_program"])} steps, '
                f'scheduled wait time={sum(wait for _, wait in self.config["rinse_program"]):g} s, '
                f'blowout_pressure={self.config["blowout_pressure"]} (used only for ctrlblow). '
                f'Program={self.config["rinse_program"]}.'
            )

            for i,(step,waittime) in enumerate(self.config['rinse_program']):
                context = f'rinseCell step {i + 1}/{len(self.config["rinse_program"])} ({step or "pause"})'
                phase = context
                step_started = time.monotonic()
                self.rinse_status = f'Rinse Program Step {i + 1}/{len(self.config["rinse_program"])}: {step} for {waittime}s'
                self.log_info(f'{context}: starting; duration={waittime:g} s.')
                if step is not None:
                    if step == 'ctrlblow':
                        self.log_info(f'{context}: commanding regulated pressure={self.config["blowout_pressure"]}.')
                        self.pctrl.set_P(self.config['blowout_pressure'])
                        self.log_info(f'{context}: pressure command completed.')
                    else:
                        self._set_channels_logged({step:True}, context)
                self.log_info(f'{context}: waiting {waittime:g} s.')
                time.sleep(waittime)
                if step is not None:
                    if step == 'ctrlblow':
                        self.log_info(f'{context}: commanding regulated pressure=0.')
                        self.pctrl.set_P(0)
                        self.log_info(f'{context}: pressure reset command completed.')
                    else:
                        self._set_channels_logged({step:False}, context)
                self.log_info(f'{context}: completed in {time.monotonic() - step_started:.1f} s.')
            phase = 'closing postsample after rinse'
            self._set_channels_logged({'postsample':False}, 'rinseCell finish')
            phase = 'raising arm'
            self.log_info('rinseCell: rinse program complete; raising arm and venting.')
            self._arm_up()
            self.state = 'READY'
            self.rinse_status = 'Not Rinsing'
            self._log_flow_state('rinseCell completed')
            self.log_info(f'rinseCell completed in {time.monotonic() - started:.1f} s; state=READY.')
        except (Exception, KeyboardInterrupt) as exc:
            self.log_error(
                f'rinseCell failed during {phase} after {time.monotonic() - started:.1f} s; '
                f'state={self.state}, rinse_status={getattr(self, "rinse_status", "unknown")}: '
                f'{type(exc).__name__}: {exc}'
            )
            raise
    
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
                out.append(list(np.transpose(ls.poll.read_load_buffer())))
            return out
    
    def set_sensor_config(self,**kwargs):
        if self.load_stopper is not None:
            if 'sensor_n' in kwargs:
                self.load_stopper[kwargs['sensor_n']].update(kwargs)
                self.load_stopper[kwargs['sensor_n']].reset()                        
            else: # assume it should apply to all
                for ls in self.load_stopper:
                    ls.config.update(kwargs)
                    ls.reset()

    def get_sensor_config(self,**kwargs):
        if self.load_stopper is not None:
            out = []
            for ls in self.load_stopper:
                out.append(ls.config.config)
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
                    if ls._app is not None:
                        ls.poll.app = self._app
                        ls.stopper.app = self._app
                    if ls._data is not None:
                        ls.poll.data = self._data
                        ls.stopper.data = self._data
                    ls.poll.start()
                    ls.stopper.start()




_DEFAULT_CUSTOM_CONFIG = {
        '_classname': 'AFL.automation.loading.PneumaticPressureSampleCell.PneumaticPressureSampleCell',
        '_args': [
                {'_classname': 'AFL.automation.loading.DigitalOutPressureController.DigitalOutPressureController',
                 '_args': [
                        {'_classname': 'AFL.automation.loading.LabJackDigitalOut.LabJackDigitalOut',
                         'intermittent_device_handle': False,
                         'port_to_write': 'TDAC4',
                         #'shared_device' = 
                         },
                        3
                 ]},
                {'_classname': 'AFL.automation.loading.PiPlatesRelay.PiPlatesRelay',
                '_args': [        
                        {
                                7:'arm-up',6:'arm-down',
                                1:'rinse1',2:'rinse2',3:'blow',4:'piston-vent',5:'postsample'
                        }]}
                ],
        'digitalin': {'_classname': 'AFL.automation.loading.PiGPIO.PiGPIO',
                        '_args': [{4:'DOOR',14:'ARM_UP',15:'ARM_DOWN'}],
                        'pull_dir':'UP'
                        },
        'load_stopper': [
                {'_classname': 'AFL.automation.loading.LoadStopperDriver.LoadStopperDriver',
                '_args': [{'_classname': 'AFL.automation.loading.LabJackSensor.LabJackSensor',
                           'port_to_read': 'AIN0',
                           'reset_port': 'DIO6'}],
                '_add_data': 'data',
                'name': 'LoadStopperDriver_sans',
                 'auto_initialize':False,
                 'sensorlabel':'afterSANS'
                },
                {'_classname': 'AFL.automation.loading.LoadStopperDriver.LoadStopperDriver',
                '_args': [{'_classname': 'AFL.automation.loading.LabJackSensor.LabJackSensor',
                           'port_to_read': 'AIN1',
                           'reset_port': 'DIO7'}],
                '_add_data': 'data',
                'name': 'LoadStopperDriver_spec',
                 'auto_initialize':False,
                 'sensorlabel':'afterSPEC'
                }
        ],
}
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
