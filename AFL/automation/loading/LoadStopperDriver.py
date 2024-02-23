from AFL.automation.APIServer.Driver import Driver
from AFL.automation.APIServer.Client import Client
from AFL.automation.loading.SensorPollingThread import SensorPollingThread
from AFL.automation.loading.SensorCallbackThread import StopLoadCBv1
from AFL.automation.loading.SensorCallbackThread import StopLoadCBv2
import warnings
import time
import pathlib
import numpy as np

import math

class LoadStopperDriver(Driver):
    '''
        Driver for stopping loads

    '''
    defaults={}
    defaults['load_speed'] = 2
    defaults['period'] = 0.05
    defaults['poll_window'] = 1000
    defaults['stopper_threshold_npts'] = 50
    defaults['stopper_threshold_v_step'] = 1
    defaults['stopper_threshold_std'] = 3.0
    defaults['stopper_min_load_time'] = 30
    defaults['stopper_timeout'] = 120
    defaults['stopper_loadstop_cooldown'] = 2
    defaults['stopper_post_detection_sleep'] = 1 
    defaults['stopper_baseline_duration'] = 10
    defaults['stopper_filepath'] = str(pathlib.Path.home()/'.afl/loadstopper_data/')
    defaults['sensorlabel'] = ''

    def __init__(self,sensor,load_client=None,load_object=None,auto_initialize=True,overrides=None,data=None,sensorlabel='',name='LoadStopperDriver'):
        self._app = None
        Driver.__init__(self,name=name,defaults=self.gather_defaults(),overrides=overrides)
        if self.data is None:
            self.data = data
        
        print(f'LoadStopperDriver started with data = {self.data}')
        self.load_object = load_object
        self.load_client = load_client

        self.sensor = sensor
        self.sensorlabel = sensorlabel
        self.poll = None
        self.stopper = None

        if auto_initialize:
            self.reset()


    def status(self):
        status = []
        status.append(f'{self.stopper.status_str}')
        return status

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self,value):
        if value is None:
            self._app = value
        else:
            self._app = value
            if self.poll is not None:
                self.poll.app = value

            if self.stopper is not None:
                self.stopper.app = value

    #@Driver.unqueued()
    #@Driver.quickbar(qb={'button_text':'calibrate', 'params':{}})
    def calibrate_sensor(self):
        return self.sensor.calibrate()

    #@Driver.unqueued()
    def read_sensor(self):
        return self.sensor.read()

    #@Driver.unqueued(render_hint='1d_plot',xlin=True,ylin=True,xlabel='time',ylabel='Signal (V)')
    def read_poll(self):
        output = np.transpose(self.poll.read())
        return list(output)

    #@Driver.unqueued(render_hint='1d_plot',xlin=True,ylin=True,xlabel='time',ylabel='Signal (V)')
    def read_poll_load(self):
        output = np.transpose(self.poll.read_load_buffer())
        return list(output)

    #@Driver.unqueued()
    #@Driver.quickbar(qb={'button_text':'reset', 'params':{}})
    def reset(self):
        self.reset_poll()
        self.reset_stopper()
        if self._app is not None:
            self.poll.app = self._app
            self.stopper.app = self._app
        self.poll.start()
        self.stopper.start()

    def reset_poll(self):
        if self.poll is not None:
            self.poll.terminate()
        self.poll = SensorPollingThread(self.sensor,period=self.config['period'],window=self.config['poll_window'],daemon=True,data=self.data)

    def reset_stopper(self):
        if self.stopper is not None:
            self.stopper.terminate()

        if self.poll is None:
            self.reset_poll()

        # self.stopper = StopLoadCBv1( 
        #     self.poll,
        #     period=self.config['period'],
        #     load_client=self.load_client,
        #     threshold_npts = self.config['stopper_threshold_npts'],
        #     threshold_v_step = self.config['stopper_threshold_v_step'],
        #     threshold_std = self.config['stopper_threshold_std'],
        #     timeout = self.config['stopper_timeout'],
        #     loadstop_cooldown = self.config['stopper_loadstop_cooldown'],
        #     post_detection_sleep = self.config['stopper_post_detection_sleep'] ,
        #     baseline_duration = self.config['stopper_baseline_duration'],
        #     filepath=self.config['stopper_filepath'],
        #     daemon=True,
        #     sensorlabel=self.sensorlabel,
        # )

        self.stopper = StopLoadCBv2( 
            self.poll,
            period=self.config['period'],
            load_client=self.load_client,
            load_object=self.load_object,
            threshold_npts = self.config['stopper_threshold_npts'],
            threshold_v_step = self.config['stopper_threshold_v_step'],
            threshold_std = self.config['stopper_threshold_std'],
            min_load_time = self.config['stopper_min_load_time'],
            timeout = self.config['stopper_timeout'],
            loadstop_cooldown = self.config['stopper_loadstop_cooldown'],
            post_detection_sleep = self.config['stopper_post_detection_sleep'] ,
            baseline_duration = self.config['stopper_baseline_duration'],
            filepath=self.config['stopper_filepath'],
            daemon=True,
            data = self.data,
            sensorlabel=self.sensorlabel,
        )

        
        

        

