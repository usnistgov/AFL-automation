from NistoRoboto.Component import Component
import numpy as np
import copy

class Mixture:
    '''
    ToDo:
        - ability to add/remove volume or mass without changing composition
        - unit support
    '''
    def __init__(self,components):
        self.components = {}
        for component in components:
            #copy so we don't modify templates
            component_copy = copy.deepcopy(component) 
            self.components[component_copy.name] = component_copy
            
    def __str__(self):
        out_str = '<Mixture v/v'
        for k,v in self.volume_fraction.items():
            out_str += f' {k}:{v:3.2f}'
        out_str +='>'
        return out_str
    
    def __repr__(self):
        return self.__str__()
    
    def __getitem__(self,name):
        return self.components[name]

    def __iter__(self):
        for name,component in self.components.items():
            yield name,component
    
    def __add__(self,other):
        mixture = copy.deepcopy(self)
        if isinstance(other,Component):
            if mixture.contains(other.name):
                mixture.components[other.name] = (mixture.components[other.name] + other)
            else:
                mixture.components[other.name] = other
        elif isinstance(other,Mixture):
            for name,component in other.components.items():
                if mixture.contains(name):
                    mixture.components[name] = (mixture.components[name] + other)
                else:
                    mixture.components[name] = other
        else:
            raise TypeError(f'Unsure how to combine Mixture with {type(other)}')
            
        return mixture
            
    def contains(self,name):
        if name in self.components:
            return True
        else:
            return False
        
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
        scale_factor = value/self.mass
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
        scale_factor = value/self.volume
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
    
    def set_mass_fractions(self,fractions,total_mass=None):
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
        
        if not (len(fractions) == len(self.components)):
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
            
    def set_concentration(self,name,concentration):
        '''
        Arguments
        ---------
        name: str
            name of component to set concentration of
        
        concentration: float
            target concentration
            
        '''
        self.components[name].mass = concentration*self.volume
        
    
