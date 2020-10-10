from NistoRoboto.shared.utilities import listify
from math import ceil,sqrt

class DummyDriver:
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




   
