from NistoRoboto.shared.utilities import listify
from NistoRoboto.APIServer.driver.Driver import Driver
from math import ceil,sqrt
import numpy as np

class DummyDriver(Driver):
    def __init__(self,name=None):
        self.app = None
        if name is None:
            self.name = 'DummyDriver'
        else:
            self.name = name

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

   
