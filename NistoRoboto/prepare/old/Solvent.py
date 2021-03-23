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

    def __str__(self):
        out_str  = '<Solvent '
        out_str += f' M={self.mass:4.3f}' if self._has_mass else ' M=None'
        out_str += f' V={self.volume:4.3f}' if self._has_volume else ' V=None'
        out_str += f' D={self.density:4.3f}' if self._has_density else ' D=None'
        out_str += '>'
        return out_str
        
