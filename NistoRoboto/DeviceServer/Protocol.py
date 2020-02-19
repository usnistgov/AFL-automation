from NistoRoboto.shared.utilities import listify
from math import ceil,sqrt

class Protocol:
    def __init__(self,name):
        self.app = None
        if name is None:
            self.name = 'Protocol'
        else:
            self.name = name
        
    def status(self):
        status = []
        return status

    def execute(self,**kwargs):
        task_name = kwargs.get('task_name',None)
        if task_name is None:
            raise ValueError('No name field in task. Don\'t know what to execute...')
        del kwargs['task_name']

        if 'device' in kwargs:
            device_name = kwargs['device']
            del kwargs['device']
            try:
                device_obj = getattr(self,device_name)
            except AttributeError:
                raise ValueError(f'Device \'{device_name}\' not found in protocol \'{self.name}\'')

            self.app.logger.info(f'Sending task \'{task_name}\' to device \'{device_name}\'!')
            getattr(device_obj,task_name)(**kwargs)
        else:
            getattr(self,task_name)(**kwargs)




   
