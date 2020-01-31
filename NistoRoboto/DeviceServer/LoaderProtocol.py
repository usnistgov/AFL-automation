from NistoRoboto.shared.utilities import listify
from math import ceil,sqrt

class SampleCellProtocol:
    def __init__(self,app,cell):
        self.app = app
        self.cell = cell
        self.pump = self.cell.pump
        self.selector = self.cell.selector
        
    def status(self):
        return ''

    def execute(self,**kwargs):
        if 'device' not in kwargs:
            raise ValueError('No device specified in task!')

        device = kwargs['device']
        del kwargs['device']

        if kwargs['device']=='pump':
            self.app.logging.debug(f'Sending task {kwargs} to pump!')
            #getattr(self.pump)(**kwargs)
        elif kwargs['device']=='selector':
            self.app.logging.debug(f'Sending task {kwargs} tos selector!')
            # getattr(self.pump)(**kwargs)
        elif kwargs['device']=='cell':
            self.app.logging.debug(f'Sending task {kwargs} to cell!')
            #getattr(self.pump)(**kwargs)
        else:
            raise ValueError(f'Device not recognized: {kwargs[\'device\']}')




   
