from NistoRoboto.shared.utilities import listify
from math import ceil,sqrt

class DummyProtocol:
    def __init__(self,name=None):
        self.app = None
        if name is None:
            self.name = 'DummyProtocol'
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




   
