import numpy as np
import copy

from NistoRoboto.prepare.Component import Component
from NistoRoboto.prepare.PrepType import PrepType,prepRegistrar
from NistoRoboto.prepare.ComponentDB import componentFactory
from NistoRoboto.shared.utilities import listify
from NistoRoboto.shared.exceptions import EmptyException,NotFoundError
from NistoRoboto.shared.units import units,enforce_units,has_units,is_volume,is_mass,AVOGADROS_NUMBER

from NistoRoboto.prepare import db

@prepRegistrar(PrepType.Solution)
class Solution:
    ''' '''
    def __init__(self,name,components,properties=None):
        self.name = name
        self.preptype=PrepType.Solution
        
        self.components = {}
        for name in listify(components):
            self.add_component_from_name(name,inplace=True)
        
        self.set_properties_from_dict(properties,inplace=True)
    
        
    def __str__(self):
        out_str = f'<Solution name:\"{self.name}\" size:{self.size}>'
        return out_str

    def __repr__(self):
        return self.__str__()
    
    def __getitem__(self,name):
        try:
            return self.components[name]
        except KeyError:
            raise KeyError(f'The component \'{name}\' is not in this solution which contains: {list(self.components.keys())}')

    def __iter__(self):
        for name,component in self.components.items():
            yield name,component
        
    def __hash__(self):
        '''Needed so Solutions can be dictionary keys'''
        return id(self)
    
    def to_dict(self):
        out_dict = {}
        out_dict['name'] = self.name
        out_dict['components'] = list(self.components.keys())
        out_dict['mg_masses'] = {}
        for k,v in self:
            out_dict['mg_masses'][k] = v.mass.to('mg').magnitude
        return out_dict
    
    @classmethod
    def from_dict(cls,in_dict):
        soln = cls(name=in_dict['name'],components=in_dict["components"])
        for k,v in in_dict['mg_masses'].items():
            soln[k].mass = v*units('mg')
        return soln
    
    def add_component_from_name(self,name,properties=None,inplace=False):
        if properties is None:
            properties = {}
            
        if inplace:
            solution = self
        else:
            solution = self.copy()
            
        try:
            solution.components[name] = db[name]
        except NotFoundError:
            if name in properties:
                #attempt to make component based on properties dict
                solution.component[name] = componentFactory(name=name,**properties[name])
            else:
                db.add_interactive(name)
                solution.components[name] = db[name]
            
        return solution
    
    def set_properties_from_dict(self,properties=None,inplace=False):
        if properties is not None:
            if inplace:
                solution = self
            else:
                solution = self.copy()
            
            for name,props in properties.items():
                if name in ['mass','volume','density']:
                    setattr(solution,name,props)
                else: #assume setting component properties
                    for prop_name,value in props.items():
                        setattr(solution.components[name],prop_name,value)
            return solution
        else:
            return self
    
    def rename_component(self,old_name,new_name,inplace=False):
        if inplace:
            solution = self
        else: 
            solution = self.copy()
        solution.components[new_name] = solution.components[old_name].copy()
        del solution.components[old_name]
        return solution

    def copy(self,name=None):
        solution = copy.deepcopy(self)
        if name is not None:
            solution.name = name
        return solution
    
    def contains(self,name):
        if name in self.components:
            return True
        else:
            return False
        
    @property
    def size(self):
        return len(self.components)
    
    @property
    def solutes(self):
        return [(name,component) for name,component in self if component.is_solute]

    @property
    def solvents(self):
        return [(name,component) for name,component in self if component.is_solvent]
    
    def __add__(self,other):
        mixture = self.copy()
        mixture.name = self.name + ' + ' + other.name
        for name,component in other:
            if mixture.contains(name):
                mixture.components[name] = (mixture.components[name] + component.copy())
            else:
                mixture.components[name] = component.copy()
        return mixture
    
    def __eq__(self,other):
        ''''Compare the mass,volume, and composition of two mixtures'''

        if other.preptype==PrepType.Solution:
            checks = []# list of true/false values that represent equality checks
            checks.append(np.isclose(self.mass,other.mass))
            checks.append(np.isclose(self.volume,other.volume))

            for name,component in self:
                checks.append(np.isclose(self[name].mass,other[name].mass))
                checks.append(np.isclose(self.mass_fraction[name],other.mass_fraction[name]))

            return all(checks)

        else:
            raise TypeError(f'Unsure how to compare Solution with {other.preptype}')

    @property
    def mass(self):
        '''Total mass of mixture.'''
        return sum([component.mass for name,component in self])

    @mass.setter
    def mass(self,value):
        '''Set total mass of mixture.'''
        value = enforce_units(value,'mass')
        scale_factor = value/self.mass
        for name,component in self: 
            component.mass = enforce_units((component.mass*scale_factor),'mass')
            
    def set_mass(self,value):
        '''Setter for inline mass changes'''
        value = enforce_units(value,'mass')
        solution = self.copy()
        solution.mass = value
        return solution
            
    @property
    def volume(self):
        '''Total volume of mixture. Only solvents are included in volume calculation'''
        return sum([component.volume for name, component in self.solvents])

    @volume.setter
    def volume(self,value):
        '''Set total volume of mixture. Mass composition will be preserved'''
        if len(self.solvents)==0:
            raise  ValueError('Cannot set Solution volume without any Solvents')

        total_volume = enforce_units(value,'volume')
        
        w = self.mass_fraction
        
        #grab the density of the first solvent
        rho_1 = self.solvents[0][1].density
        
        denom = [1.0]
        #skip the first solvent
        for name,component in self.solvents[1:]:
            rho_2 = component.density
            denom.append(-w[name]*(1-rho_1/rho_2))
            
        for name,component in self.solutes:
            denom.append(-w[name])
        
        total_mass = enforce_units(total_volume*rho_1/sum(denom),'mass')
        self.mass = total_mass
    
    def set_volume(self,value):
        '''Setter for inline volume changes'''
        solution = self.copy()
        solution.volume = value
        return solution
        
    @property
    def solvent_sld(self):
        sld = []
        for name,vfrac in self.volume_fraction.items():
            sld.append(vfrac*self.components[name].sld)
        return sum(sld)
                
    @property
    def solvent_density(self):
        m = self.solvent_mass
        v = self.solvent_volume
        return enforce_units(m/v,'density')
    
    @property
    def solvent_volume(self):
        return sum([component.mass/component.density for name, component in self.solvents])
    
    @property
    def solvent_mass(self):
        return sum([component.mass for name, component in self.solvents])
    
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
        for name,component in self:
            mass_fraction[name] = component.mass/total_mass
        return {name:component.mass/total_mass for name,component in self}
    
    @mass_fraction.setter
    def mass_fraction(self,target_mass_fractions):
        '''Mass fraction of components in mixture

        Returns
        -------
        mass_fraction: dict
        Component mass fractions
        '''
        missing_comp = list(self.components.keys())
        for comp in target_mass_fractions.keys():
            if comp in missing_comp:
                missing_comp.remove(comp)
        
        if len(missing_comp)>1:
            raise ValueError(f'Must specify at least {self.size-1} mass fractions for mixture of size {self.size}')
        elif len(missing_comp)==1:
            target_mass_fractions[missing_comp[0]] = 1.0 - sum(target_mass_fractions.values())
        
        total_mass = self.mass
            
        for name,fraction in target_mass_fractions.items():
            self.components[name].mass = fraction*total_mass
    
    @property
    def volume_fraction(self):
        '''Volume fraction of solvents in mixture

        Returns
        -------
        solvent_fraction: dict
        Component mass fractions
        '''
        total_volume = self.volume
        return {name:component.volume/total_volume for name,component in self.solvents}
    
    @volume_fraction.setter
    def volume_fraction(self,vfrac_dict):
        '''Volume fraction of components in mixture

        Returns
        -------
        volume_fraction: dict
        Component volume fractions
        '''
        missing_comp = [name for name,component in self.solvents]
        for comp in vfrac_dict.keys():
            if comp in missing_comp:
                missing_comp.remove(comp)
        
        if len(missing_comp)>1:
            raise ValueError(f'Must specify at least {len(self.sovlents)-1} volume fractions for mixture with {len(self.solvents)}')
        elif len(missing_comp)==1:
            vfrac_dict[missing_comp[0]] = 1.0 - sum(vfrac_dict.values())
        
        total_volume = self.volume
            
        for name,fraction in vfrac_dict.items():
            self.components[name].volume = fraction*total_volume
            
    @property
    def concentration(self):
        total_volume = self.volume
        return {name:component.mass/total_volume for name,component in self}
    
    @concentration.setter
    def concentration(self,conc_dict):
        total_volume = self.volume
        for name,conc in conc_dict.items():
            conc = enforce_units(conc,'concentration')
            self.components[name].mass = enforce_units(conc*total_volume,'mass')
    
    @property
    def molarity(self):
        total_volume = self.volume
        result = {}
        for name,component in self:
            if component._has_formula:
                result[name] = enforce_units(component.moles/total_volume,'molarity')
        return result
    
    @molarity.setter
    def molarity(self,molarity_dict):
        total_volume = self.volume
        for name,molarity in molarity_dict.items():
            if not self.components[name]._has_formula:
                raise ValueError(f'Attempting to set molarity of component without formula: {name}')
            else:
                molar_mass = self.components[name].formula.molecular_mass*AVOGADROS_NUMBER*units('g')
                self.components[name].mass = enforce_units(molarity*molar_mass*total_volume,'mass')
    
    def measure_out(self,amount,deplete=False):
        '''Create solution with identical composition at new total mass/volume'''
        
        if not has_units(amount):
            raise ValueError('Must supply units to measure_out')
        
        if is_volume(amount):
            solution = self.copy()
            solution.volume = amount
        elif is_mass(amount):
            solution = self.copy()
            solution.mass = amount
        else:
            raise ValueError(f'Must supply measure_out with a volume or mass not {amount.dimensionality}')
            
        if deplete:
            if self.volume>solution.volume:
                self.volume = self.volume - solution.volume
            else:
                raise EmptyException()
        return solution

