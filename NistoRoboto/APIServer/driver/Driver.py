from NistoRoboto.shared.utilities import listify
from math import ceil,sqrt
import inspect 
def makeRegistrar():
    functions = []
    decorator_kwargs = {}
    function_info = {}
    def registrarfactory(**kwargs):
        #print(f'Set up registrar-factory with registry {registry}...')
        def registrar(func):#,render_hint=None):  #kwarg = kwargs):
            functions.append(func.__name__)
            decorator_kwargs[func.__name__]=kwargs

            argspec = inspect.getfullargspec(func)
            if argspec.defaults is None:
                fargs = argspec.args
                fkwargs = []
            else:
                fargs = argspec.args[:-len(argspec.defaults)]
                fkwargs = [(i,j) for i,j in zip(argspec.args[-len(argspec.defaults):],argspec.defaults)]
            if fargs[0] == 'self':
                del fargs[0]
            function_info[func.__name__] = {'args':fargs,'kwargs':fkwargs,'doc':func.__doc__}
            return func  # normally a decorator returns a wrapped function, 
                         # but here we return func unmodified, after registering it
        return registrar
    registrarfactory.functions = functions
    registrarfactory.decorator_kwargs = decorator_kwargs
    registrarfactory.function_info = function_info
    return registrarfactory


class Driver:
    unqueued = makeRegistrar()
    queued = makeRegistrar()
    def __init__(self,name):
        self.app = None
        if name is None:
            self.name = 'Driver'
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


   
