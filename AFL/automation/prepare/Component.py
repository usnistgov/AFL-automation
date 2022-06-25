import numpy as np
import periodictable
import copy
import numbers
from pyparsing import ParseException

from AFL.automation.shared.units import units, AVOGADROS_NUMBER, enforce_units
from AFL.automation.prepare.PrepType import PrepType


class Component(object):
    '''Base class for all materials
    
    This class defines all of the basic properties and methods to be shared across material objects
    
    '''
    def __init__(self,name,description):
        self.name = name
        self.description = description
        self._mass    = 1.0*units('mg')
        self._density = None
        self._formula = None
        self._sld     = None
        self.preptype = PrepType.BaseComponent
        
    def emit(self):
        return {
        'name':self.name,
        'description':self.description,
        'density':self.density,
        'formula':self.formula,
        'sld':self.sld,
        'preptype':self.preptype
        }
        
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
    
    def copy(self):
        return copy.deepcopy(self)

    def __iter__(self):
        '''Dummy iterator to mimic behavior of Mixture.'''
        for name,component in [(self.name,self)]:
            yield name,component
    
    @property
    def mass(self):
        return self._mass
    
    @mass.setter
    def mass(self,value):
        enforce_units(value,'mass')
        self._mass = value
        
    def set_mass(self,value):
        '''Setter for inline mass changes'''
        component = self.copy()
        component.mass = value
        return component
    
    @property
    def volume(self):
        if self._has_density:
            return enforce_units(self._mass/self._density,'volume')
        else:
            return None
        
    @volume.setter
    def volume(self,value):
        enforce_units(value,'volume')
        
        if not self._has_density:
            raise ValueError('Can\'t set volume without specifying density')
        else:
            self.mass = enforce_units(value*self._density,'mass')
            
    def set_volume(self,value):
        '''Setter for inline volume changes'''
        component = self.copy()
        component.volume = value
        return component
            
    @property
    def density(self):
        return self._density
        
    @density.setter
    def density(self,value):
        enforce_units(value,'density')
        self._density = value
            
    @property
    def formula(self):
        return self._formula
    
    @formula.setter
    def formula(self,value):
        if value is None:
            self._formula = None
        else:
            try:
                self._formula = periodictable.formula(value)
            except (ValueError,ParseException):
                self._formula = None
            
    @property
    def moles(self):
        if self._has_formula:
            return self._mass/(self.formula.molecular_mass*units('g'))/AVOGADROS_NUMBER
        else:
            return None
            
    @property
    def sld(self):
        if self._sld is not None:
            return self._sld
        elif self._has_formula and self._has_density:
            self.formula.density = self.density.to('g/ml').magnitude
            sld = self.formula.neutron_sld(wavelength=5.0)[0]
            return sld*1e-6*units('angstrom^(-2)')
        else:
            return None
        
    @sld.setter
    def sld(self,value):
        self._sld = value
        
    @property
    def is_solute(self):
        return self.preptype==PrepType.Solute

    @property
    def is_solvent(self):
        return self.preptype==PrepType.Solvent
    
    @property
    def _has_volume(self):
        return (self._volume is not None)
    
    @property
    def _has_density(self):
        return (self._density is not None)
    
    @property
    def _has_formula(self):
        return (self._formula is not None)
    
    @property
    def _has_sld(self):
        return ((self._sld is not None) or (self._has_formula and self._has_density))
    
    def __add__(self,other):
        
        if not (self.preptype==other.preptype):
            raise ValueError(f'Can only add components of the same preptype. Not {self.preptype} and {other.preptype}')
        
        if not (self.name == other.name):
            raise ValueError(f'Can only add components of the same name. Not {self.name} and {other.name}')
        
        if not (self.density == other.density):
            raise ValueError(f'Density mismatch in component.__add__: {self.density} and {other.density}')

        component = copy.deepcopy(self)
        component.mass = enforce_units(component._mass + other._mass,'mass')
        return component
    
    
