import numpy as np
import periodictable
import copy
import numbers
from pyparsing import ParseException

from NistoRoboto.shared.units import units, AVOGADROS
from NistoRoboto.prep.Component import Component
from NistoRoboto.prep.types import types


class Solute(Component):
    '''Specialization class for solute components
    
    '''
    def __init__(self,name,mass=None,density=None,formula=None):
        super().__init__(name=name,mass=mass,formula=formula,density=density,volume=None)
        self._volume=None
        self.type=types.Solute

    def __str__(self):
        out_str  = '<Solute '
        out_str += f' M={self.mass:4.3f}' if self._has_mass else ' M=None'
        out_str += '>'
        return out_str
    
    def __repr__(self):
        return self.__str__()

    @property
    def mass(self):
        return self._mass
    
    @mass.setter
    def mass(self,value):
        self._mass = value

    def set_mass(self,mass):
        '''Setter for inline volume changes'''
        component = self.copy()
        component.mass = mass
        return component

    @property
    def volume(self):
        return None
    
    @volume.setter
    def volume(self,value):
        raise ArgumentError('Solute cannot have volume')

    def set_volume(self,volume):
        '''Setter for inline volume changes'''
        raise ArgumentError('Solute cannot have volume')
    
    @property
    def _has_volume(self):
        return False
    
    def __mul__(self,factor):
        if not isinstance(factor,numbers.Number):
            raise TypeError(f'Can only multiply Component by numerical scale factor, not {type(factor)}')
        component = copy.deepcopy(self)
        component._mass *= factor
        return component
    
    def __rmul__(self,factor):
        return self.__mul__(factor)
            
    def _add_volume(self,other):
        raise ValueError('Solute cannot have volume')
        
    def _add_all_properties(self,other):
        self._add_mass(other)
        
            
