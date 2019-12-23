from Roboto.Component import Component
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
        return sum([component.mass for name,component in self.components.items()])
    
    @property
    def volume(self):
        return sum([component.volume for name,component in self.components.items()])
    
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
        total_mass = self.mass
        return {name:component.mass/total_mass for name,component in self.components.items()}
    
    @property
    def volume_fraction(self):
        total_volume = self.volume
        return {name:component.volume/total_volume for name,component in self.components.items()}
    
    @property
    def concentration(self):
        total_volume = self.volume
        return {name:component.mass/total_volume for name,component in self.components.items()}
    
    def set_mass_fractions(self,total_mass,fractions):
        '''
        Arguments
        ---------
        total_mass: float
            Total mass of mixture
        
        fractions: dict
            Dictionary of component fractions. The number of elements of the 
            dictionary must match the number of components in the mixture
            
        '''
        
        if not (len(fractions) == len(self.components)):
            raise ValueError('Fraction dictionary doesn\'t match size of mixture')
        
        normalization = sum(fractions.values()) # can't trust users to give sane fractional values
        for name,fraction in fractions.items():
            self.components[name].mass = (fraction/normalization)*total_mass
        
    def set_volume_fractions(self,total_volume,fractions):
        '''
        Arguments
        ---------
        total_volume: float
            Total volume of mixture
        
        fractions: dict
            Dictionary of component fractions. The number of elements of the 
            dictionary must match the number of components in the mixture
            
        '''
        
        if not (len(fractions) == len(self.components)):
            raise ValueError('Fraction dictionary doesn\'t match size of mixture')
        
        
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
        
    
