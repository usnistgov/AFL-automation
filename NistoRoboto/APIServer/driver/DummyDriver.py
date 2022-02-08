from NistoRoboto.shared.utilities import listify
from NistoRoboto.APIServer.driver.Driver import Driver
from math import ceil,sqrt
import numpy as np
import pathlib

class DummyDriver(Driver):
    defaults = {}
    defaults['speed of light'] = 3.0e8
    defaults['density of water'] = 1.0
    def __init__(self,name=None,overrides=None):
        self.app = None
        if name is None:
            name = 'DummyDriver'
        Driver.__init__(self,name=name,defaults=self.gather_defaults(),overrides=overrides)

    def status(self):
        status = []
        status.append('Pippettors: pipetting')
        status.append('Pumps: pumping')
        status.append('Selectors: selecting')
        status.append('Neutrons: scattering')
        return status

    def execute(self,**kwargs):
        if self.app is not None:
            self.app.logger.debug(f'Executing task {kwargs}')

        if 'task_name' in kwargs:
            if kwargs['task_name'] == 'error':
                raise RuntimeError()
            elif kwargs['task_name'] in ('get_parameter','get_parameters','set_parameter','set_parameters'):
                task_name = kwargs.get('task_name',None)
                del kwargs['task_name']
                return_val = getattr(self,task_name)(**kwargs)
                return return_val

    @Driver.queued()
    def test_command1(self,kwarg1=None,kwarg2=True):
        '''A test command with positional and keyword parameters'''
        pass

    @Driver.queued()
    def test_command2(self,kwarg1=False,kwarg2=False,kwarg3=True):
        '''A test command with positional and keyword parameters'''
        pass

    @Driver.unqueued()
    def how_many(self,**kwargs):
        self.app.logger.debug(f'Call to how_many with kwargs: {kwargs}')
        if 'count' in kwargs:
            return f'Not sure, but probably something like {kwargs["count"]}'
        else:
            return "Not sure"

    @Driver.unqueued(render_hint='1d_plot',xlin=True,ylin=True,xlabel="random x",ylabel="random y",title="random data")
    def test_plot(self,**kwargs):
        self.app.logger.debug(f'Call to test_plot with kwargs: {kwargs}')
        return (np.random.rand(500,2))


    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def test_image(self,**kwargs):
        self.app.logger.debug(f'Call to test_image with kwargs: {kwargs}')
        return np.random.rand(1024,1024)


    @Driver.quickbar(qb={'button_text':'Reset Tank Levels',
        'params':{
        'rinse1':{'label':'Rinse1 (mL)','type':'float','default':950},
        'rinse2':{'label':'Rinse2 (mL)','type':'float','default':950},
        'waste':{'label':'Waste (mL)','type':'float','default':0}
        }})
    @Driver.unqueued()
    def dummy_reset_tank_levels(self,rinse1=950,rinse2=950,waste=0):
        pass

    @Driver.quickbar(qb={'button_text':'Load Sample',
        'params':{'sampleVolume':{'label':'Sample Volume (mL)','type':'float','default':0.3}}})
    def loadSample(self,cellname='cell',sampleVolume=0):
        pass
