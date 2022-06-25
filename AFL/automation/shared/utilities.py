import types
import datetime
from AFL.automation.shared.units import has_units


def listify(obj):
    if isinstance(obj, str) or not hasattr(obj, "__iter__"):
        obj = [obj]
    elif has_units(obj):
        #special handling for pint quanitites whch, for some reason
        #have __iter__ defined for single values...
        try:
            len(obj)
        except TypeError:
            obj = [obj]
    return obj

def tprint(in_str):
    now = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
    print(f'[{now}] {in_str}')
    
def makeRegistar():
    registry = {}
    def registrarDecorator(prepType):#the actual decorator
        def registrar(cls):#function that interacts with cls
            registry[prepType] = cls
            return cls #return unwrapped class after registering
        return registrar
    registrarDecorator.registry = registry
    return registrarDecorator

