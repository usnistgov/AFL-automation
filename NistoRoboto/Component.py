import numpy as np
import periodictable
import copy
import numbers
from pyparsing import ParseException

class Component(object):
    '''Base class for all materials
    
    This class defines all of the basic properties and methods to be shared across material objects
    
    '''
    def __init__(self,name,mass=None,volume=None,density=None,formula=None):
        self.name    = name
        self.density = density
        
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

    def __str__(self):
        mass    = self.mass if self._has_mass() else -1
        volume  = self.volume if self._has_volume() else -1
        density = self.density if self._has_density() else -1
        return f'<Component M={mass:3.2f} V={volume:3.2f} D={density:3.2f}>'
    
    def __repr__(self):
        return self.__str__()
    
    @property
    def mass(self):
        return self._mass
    
    @mass.setter
    def mass(self,value):
        self._mass = value
        if self._has_mass() and self._has_density():
            self._volume = self._mass/self.density

    @property
    def volume(self):
        return self._volume
    
    @volume.setter
    def volume(self,value):
        self._volume = value
        if self._has_volume() and self._has_density():
            self._mass = self._volume*self.density
    
    @property
    def sld(self):
        if self._has_formula() and self._has_density():
            
            #try to coonvert units and them strip them
            #XXX This is hacky and needs to be changed
            try:
                self.formula.density = self.density.to('g/ml').magnitude
            except AttributeError:
                self.formula.density = self.density
                
            # neutron_sld returns a 3-tuple with (real, imag, incoh)
            # wavelength doesn't matter for real_sld
            return self.formula.neutron_sld(wavelength=5.0)[0]
        else:
            return None
            
    def _has_density(self):
        return (self.density is not None)
    
    def _has_volume(self):
        return (self.volume is not None)
    
    def _has_mass(self):
        return (self.mass is not None)
    
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
        if self._has_volume() and other._has_volume():
            self._volume = self.volume + other.volume
        else:
            self._volume = None
        
    def _add_mass(self,other):
        if self._has_mass() and other._has_mass():
            self._mass = self.mass + other.mass
        else:
            self._mass = None
        
    def _add_density(self,other):
        if self._has_mass() and other._has_mass() and self._has_density() and other._has_density():
            self.density = (self.mass + other.mass)/(self.mass/self.density + other.mass/other.density)
        else:
            self.density = None
            
    def _add_all_properties(self,other):
        self._add_volume(other)
        self._add_mass(other)
        self._add_density(other)
        
    def __add__(self,other):
        if not isinstance(other,Component):
            raise ValueError('Can only add identical component objects!')

        if self.name == other.name:
            component = copy.deepcopy(self)
            component._add_all_properties(other)
            return component
        else:
            raise ValueError('Can only add identical components!')
            
