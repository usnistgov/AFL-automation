from NistoRoboto.prep.Component import Component
from NistoRoboto.shared.exceptions import EmptyException
import numpy as np
import copy

from NistoRoboto.shared.units import units,AVOGADROS
from NistoRoboto.prep.Mixture import Mixture
from NistoRoboto.prep.types import types
from NistoRoboto.shared.utilities import listify


class Solution(Mixture):
    ''' '''
    def __init__(self,components=None):
        self.type=types.Solution

        if components is None:
            components = []
        else:
            components = listify(components)

        self.components = {}
        for component in components:
            #copy so we don't modify templates
            component_copy = component.copy()
            self.components[component_copy.name] = component_copy
            
    def __str__(self):
        out_str = '<Solution m/m'
        mass_fraction = self.mass_fraction
        for name,component in self:
            mfrac = mass_fraction.get(name,None)
            if mfrac is None:
                out_str += f' {name}:NoMass'
            else:
                out_str += f' {name}:{mfrac:4.3f}'
        out_str +='>'
        return out_str

    @property
    def mass(self):
        '''Total mass of mixture. Components with mass = None will be ignored.'''
        masses = []
        for name,component in self.components.items(): 
            if component._has_mass:
                masses.append(component.mass)
        return sum(masses)

    @mass.setter
    def mass(self,value):
        '''Set total mass of mixture. Components with no mass specified will be ignored.'''
        if self.mass>0:
            scale_factor = value/self.mass
        else:
            scale_factor = 0

        for name,component in self.components.items(): 
            if component._has_mass:
                component.mass = (component.mass*scale_factor)
    
    @property
    def volume(self):
        '''Total volume of mixture. Components with no volume specified will be ignored.'''
        volumes = []
        for name,component in self.components.items(): 
            if component._has_volume:
                volumes.append(component.volume)
        return sum(volumes)

    @volume.setter
    def volume(self,value):
        '''Set total volume of mixture. Components with no volume specified will be ignored.'''
        if self.volume>0:
            scale_factor = value/self.volume
        else:
            scale_factor = 0
        for name,component in self.components.items(): 
            if component._has_volume:
                component.volume = (component.volume*scale_factor)
    
    @property
    def density(self):
        return self.mass/sum([component.mass/component.density for name,component in self.components.items()])
    
    @property
    def sld(self):
        sld = []
        for name,vfrac in self.volume_fraction.items():
            try:
                vfrac = vfrac.magnitude
            except AttributeError:
                pass
            sld.append(vfrac*self.components[name].sld)
        return sum(sld)
    
    @property
    def mass_fraction(self):
        '''Mass fraction of components in mixture

        Returns
        -------
        mass_fraction: dict
        Component mass fractions
        '''
        total_mass = self.mass
        mass_fraction = {}
        for name,component in self.components.items():
            if component._has_mass:
                mass_fraction[name] = component.mass/total_mass
        return mass_fraction
    
    @property
    def volume_fraction(self):
        '''Volume fraction of components in mixture

        Returns
        -------
        volume_fraction: dict
        Component volume fractions
        '''
        total_volume = self.volume
        volume_fraction = {}
        for name,component in self.components.items():
            if component._has_volume:
                volume_fraction[name] = component.volume/total_volume
        return volume_fraction
    
    @property
    def concentration(self):
        total_volume = self.volume
        return {name:component.mass/total_volume for name,component in self.components.items()}

    @property
    def molarity(self,units='millimolar'):
        total_volume = self.volume
        result = {name:component.moles/total_volume for name,component in self.components.items() if component._has_formula}
        try:
            result = {k:v.to(units) for k,v in result.items()}
        except AttributeError:
            #units not defined
            pass
        return result
    
    def set_mass_fractions(self,total_mass=None,**fractions):
        '''
        Arguments
        ---------
        
        fractions: dict
            Dictionary of component fractions. The number of elements of the 
            dictionary must match the number of components in the mixture

        total_mass: float
            Total mass of mixture. If not set, the current total mass of the
            mixture is used
            
        '''
        raise NotImplemented()
        
        if not (len(fractions) >= (len(self.components)-1)):
            raise ValueError('Fraction dictionary doesn\'t match size of mixture')

        if total_mass is None:
            total_mass = self.mass
        
        normalization = sum(fractions.values()) # can't trust users to give sane fractional values
        for name,fraction in fractions.items():
            self.components[name].mass = (fraction/normalization)*total_mass
        
    def set_volume_fractions(self,fractions,total_volume=None):
        '''
        Arguments
        ---------
        fractions: dict
            Dictionary of component fractions. The number of elements of the 
            dictionary must match the number of components in the mixture

        total_volume: float
            Total volume of mixture. If not set, the current total volume of 
            the mixture is used.
        
        '''
        
        if not (len(fractions) == sum([c._has_volume for name,c in self.components.items()])):
            raise ValueError('Fraction dictionary doesn\'t match size of mixture')

        if total_volume is None:
            total_volume = self.volume
        
        normalization = sum(fractions.values()) # can't trust users to give sane fractional values
        for name,fraction in fractions.items():
            self.components[name].volume = (fraction/normalization)*total_volume
            
    def set_mass_concentration(self,name,concentration,by_dilution=False):
        '''
        Arguments
        ---------
        name: str
            name of component to set concentration of
        
        concentration: float
            target concentration
            
        '''
        if by_dilution:
            self.volume = self.components[name].mass / concentration
        else:
            self.components[name].mass = concentration*self.volume

    def set_molarity(self,name,molarity,by_dilution=False):
        '''
        Arguments
        ---------
        name: str
            name of component to set molarity of
        
        molarity: float
            target molarity in mol/L
            
        '''
        if self.components[name].formula is None:
            raise RuntimeError('Cannot set molarity without formula defined')

        molar_mass = self.components[name].formula.molecular_mass*AVOGADROS
        self.components[name].mass = molarity*molar_mass*self.volume #Assumes volume is in mL

    @property
    def solutes(self):
        return [c for n,c in self.components.items() if c.is_solute()]

    @property
    def solvents(self):
        return [c for n,c in self.components.items() if c.is_solvent()]

    def remove_volume(self,amount,deplete=False):
        '''Remove volume from mixture without changing composition

        Returns
        -------
        Mixture object with removed volume at identical composition 
        '''
        if self.volume<amount:
            raise EmptyException(f'Volume of mixture ({self.volume}) less than removed amount ({amount})')

        if not all([component._has_volume for name,component in self]):
           raise RuntimeError('Can\'t remove volume from mixture without all volumes specified')
       
        self.volume = self.volume - amount
        removed = self.copy()
        removed.volume = amount
        return removed

    def remove_mass(self,amount):
        '''Remove mass from mixture without changing composition

        Returns
        -------
        Mixture object with removed mass at identical composition 
        '''
        if self.mass<amount:
            raise EmptyException(f'Mass of mixture ({self.mass}) less than removed amount ({amount})')

        if not all([component._has_mass for name,component in self]):
           raise RuntimeError('Can\'t remove mass from mixture without all masses specified')
       
        self.mass = self.mass - amount

        removed = self.copy()
        removed.mass = amount
        return removed

        

