import numpy as np
import periodictable
import copy
import numbers
from pyparsing import ParseException

from NistoRoboto.shared.units import units
from NistoRoboto.prep.types import types

AVOGADROS_NUMBER = 6.0221409e+23*units('1/mol')

class Component(object):
    '''Base class for all materials
    
    This class defines all of the basic properties and methods to be shared across material objects
    
    '''
    def __init__(self,name,mass=None,volume=None,density=None,formula=None):
        self.name    = name
        self.density = density
        self.type = types.BaseComponent
        
        if (mass is None) and (volume is None):
            # use hidden variables to avoid property setting Nonsense
            self._mass = None
            self._volume = None
        elif volume is None:
            # volume will be set in property.setter if density is set
            self. _volume = None
            self.mass    = mass
        elif mass is None:
            # mass will be set in property.setter if density is set
            self._mass = None
            self.volume  = volume
        else:
            # use hidden variables to avoid property setting Nonsense
            self._mass = mass
            self._volume = volume
        
        # try to set up periodictable object for sld calculation
        if formula is None:
            formula = name
        try:
            self.formula = periodictable.formula(formula)
        except ValueError:
            self.formula = None
        except ParseException:
            self.formula = None

    def is_solute(self):
        return self.type==types.Solute

    def is_solvent(self):
        return self.type==types.Solvent

    def copy(self):
        return copy.deepcopy(self)

    def __iter__(self):
        '''Dummy iterator to mimic behavior of Mixture.'''
        for name,component in [(self.name,self)]:
            yield name,component
    
    def __str__(self):
        out_str  = '<Component '
        out_str += f' M={self.mass:4.3f}' if self._has_mass else ' M=None'
        out_str += f' V={self.volume:4.3f}' if self._has_volume else ' V=None'
        out_str += f' D={self.density:4.3f}' if self._has_density else ' D=None'
        out_str += '>'
        return out_str
    
    def __repr__(self):
        return self.__str__()

    def __hash__(self):
        '''Needed so Components can be dictionary keys'''
        return id(self)

    @property
    def moles(self):
        if self._has_formula and self._has_mass:
            return self._mass/(self.formula.molecular_mass*ureg('g'))/AVOGADROS_NUMBER
        else:
            return None

    @property
    def mass(self):
        return self._mass
    
    @mass.setter
    def mass(self,value):
        self._mass = value
        if self._has_mass and self._has_density:
            self._volume = self._mass/self.density
        else:
            self._volume = None

    def set_mass(self,mass):
        '''Setter for inline volume changes'''
        component = self.copy()
        component.mass = mass
        return component

    @property
    def volume(self):
        return self._volume
    
    @volume.setter
    def volume(self,value):
        self._volume = value

        if self._has_volume and self._has_density:
            self._mass = self._volume*self.density
        else:
            self._mass = None

    def set_volume(self,volume):
        '''Setter for inline volume changes'''
        component = self.copy()
        component.volume = volume
        return component
    
    @property
    def sld(self):
        if self._has_formula and self._has_density:
            
            self.formula.density = self.density.to('g/ml').magnitude
            # neutron_sld returns a 3-tuple with (real, imag, incoh)
            # wavelength doesn't matter for real_sld
            return self.formula.neutron_sld(wavelength=5.0)[0]
        else:
            return None

    @property
    def _has_density(self):
        return (self.density is not None)
    
    @property
    def _has_volume(self):
        # return ((self.volume is not None) and (self.volume>0))
        return (self.volume is not None) 
    
    @property
    def _has_mass(self):
        # return ((self.mass is not None) and (self.mass>0))
        return (self.mass is not None) 
    
    @property
    def _has_formula(self):
        return (self.formula is not None)
    
    def __mul__(self,factor):
        if not isinstance(factor,numbers.Number):
            raise TypeError(f'Can only multiply Component by numerical scale factor, not {type(factor)}')
        component = copy.deepcopy(self)
        component._volume *= factor
        component._mass *= factor
        return component
    
    def __rmul__(self,factor):
        return self.__mul__(factor)
            
    def _add_volume(self,other):
        if self._has_volume and other._has_volume:
            self._volume = self.volume + other.volume
        else:
            self._volume = None
        
    def _add_mass(self,other):
        if self._has_mass and other._has_mass:
            self._mass = self.mass + other.mass
        else:
            self._mass = None
        
    def _add_density(self,other):
        if self._has_mass and other._has_mass and self._has_density and other._has_density:
            self.density = (self.mass + other.mass)/(self.mass/self.density + other.mass/other.density)
        else:
            self.density = None
            
    def _add_all_properties(self,other):
        self._add_volume(other)
        self._add_mass(other)
        self._add_density(other)
        
    def __add__(self,other):
        if not hasattr(other,'_add_all_properties'):
            raise ValueError('Can only add components of same type (i.e., name)')

        if self.name == other.name:
            component = copy.deepcopy(self)
            component._add_all_properties(other)
            return component
        else:
            raise ValueError('Can only add components of same type (i.e., name)')
            
