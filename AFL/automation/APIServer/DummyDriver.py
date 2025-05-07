from AFL.automation.shared.utilities import listify
from AFL.automation.APIServer.Driver import Driver
from math import ceil,sqrt
import numpy as np
import pathlib
import time

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
    
    '''def execute(self,**kwargs):
        try:
           Driver.execute(self,**kwargs)
        except AttributeError:
            if self.app is not None:
                self.app.logger.debug(f'Executing non-existent task {kwargs}')
            time.sleep(0.5)
            return 0
    
    #add the get_well_plate here
    '''
    @Driver.queued()
    def test_command1(self,kwarg1=None,kwarg2=True):
        '''A test command with positional and keyword parameters'''
        pass

    @Driver.queued()
    def test_command2(self,kwarg1=False,kwarg2=False,kwarg3=True):
        '''A test command with positional and keyword parameters'''
        pass
    @Driver.queued()
    def test_command_sets_data(self,kwarg1=False,kwarg2=False,kwarg3=True):
        '''A test command with positional and keyword parameters'''
        if self.data is not None:
            self.data['kwarg1'] = kwarg1
            self.data['kwarg2'] = kwarg2
            self.data['kwarg3'] = kwarg3
        return np.random.randn(10)
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

    @Driver.quickbar(qb={'button_text':'Submit',
        'params':{
        'text_field':{'label':'How many(text)?','type':'text','default':'Three'},
        'int_field':{'label':'How many(int)?','type':'int','default':3},
        'float_field':{'label':'How many(float)?','type':'float','default':3.14},
        'bool_field':{'label':'Any(bool)?','type':'bool','default':True},
        }})
    def quickbar_test(self,text_field="Three",int_field=3,float_field=3.14,bool_field=True):
        pass

    @Driver.quickbar(qb={'button_text':'Just A Button'})
    def quickbar_test2(self):
        pass

    @Driver.quickbar(qb={'button_text':'Reset Tank Levels',
        'params':{
        'rinse1':{'label':'Rinse1 (mL)','type':'float','default':950},
        'rinse2':{'label':'Rinse2 (mL)','type':'float','default':950},
        'waste': {'label':'Waste (mL)','type':'float','default':0}
        }})
    @Driver.unqueued()
    def dummy_reset_tank_levels(self,rinse1=950,rinse2=950,waste=0):
        pass

    @Driver.quickbar(qb={'button_text':'Load Sample',
        'params':{'sampleVolume':{'label':'Sample Volume (mL)','type':'float','default':0.3}}})
    def loadSample(self,cellname='cell',sampleVolume=0):
        pass

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
