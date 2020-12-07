import numpy as np
import periodictable
import copy
import numbers
from pyparsing import ParseException

from NistoRoboto.shared.units import units
from NistoRoboto.prep.Component import Component
from NistoRoboto.prep.types import types

class Solvent(Component):
    '''Component Specialization for Solvents'''
    def __init__(self,name,mass=None,volume=None,density=None,formula=None):
        super().__init__(name=name,mass=mass,volume=volume,formula=formula,density=density)
        self.type = types.Solvent
        
