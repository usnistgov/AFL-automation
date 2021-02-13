from NistoRoboto.shared.utilities import listify
from NistoRoboto.APIServer.driver.Driver import Driver
from math import ceil,sqrt

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

    @Driver.unqueued
    def how_many(self,**kwargs):
        if 'count' in kwargs:
            return f'Not sure, but probably something like {kwargs["count"]}'
        else:
            return "Not sure"

   
