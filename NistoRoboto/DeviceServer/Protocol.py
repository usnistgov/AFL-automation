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
        #execute the command
        del kwargs['task_name']
        getattr(self,task_name)(**kwargs)




   
