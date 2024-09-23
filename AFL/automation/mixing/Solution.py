import numpy as np
import copy
import warnings
from typing import Optional, Dict

import pint

from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.mixing.Component import Component
from AFL.automation.shared.exceptions import EmptyException,NotFoundError
from AFL.automation.shared.units import units,enforce_units,has_units,is_volume,is_mass,AVOGADROS_NUMBER


class Solution:
    """ """
    def __init__(
            self,
            name: str,
            total_mass: Optional[pint.Quantity]=None,
            total_volume: Optional[pint.Quantity]=None,
            masses: Optional[Dict]=None,
            volumes: Optional[Dict]=None,
            concentrations: Optional[Dict]=None,
            ):
        self.name = name
        self.components = {}

        if masses is not None:
            for name,mass in masses.items():
                self.add_component_from_name(name)
                self.components[name].mass = mass

        if volumes is not None:
            for name,volume in volumes.items():
                self.add_component_from_name(name)
                self.components[name].volume = volume

        if concentrations is not None:
            if (self.volume is None) or (self.volume.magnitude==0):
                raise ValueError('Cannot set concentrations without setting volume')
            for name,conc in concentrations.items():
                self.add_component_from_name(name)
            self.concentration = concentrations

        if total_mass is not None:
            self.mass = total_mass

        if total_volume is not None:
            self.volume = total_volume


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
        """Needed so Solutions can be dictionary keys"""
        return id(self)
    
    def to_dict(self):
        out_dict = {}
        out_dict['name'] = self.name
        out_dict['components'] = list(self.components.keys())
        out_dict['mg_masses'] = {}
        for k,v in self:
            out_dict['mg_masses'][k] = v.mass.to('mg').magnitude
        return out_dict
    
    def add_component_from_name(self,name):
        if name not in self.components:
            try:
                mixdb = MixDB.get_db()
            except ValueError:
                # attempt to instantiate from default location
                mixdb = MixDB()

            try:
                self.components[name] = Component(**mixdb.get_component(name))
            except NotFoundError:
                raise

            return

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
        return [(name,component) for name,component in self if not component.has_volume]

    @property
    def solvents(self):
        return [(name,component) for name,component in self if component.has_volume]
    
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
        """Compare the mass,volume, and composition of two mixtures"""

        # list of true/false values that represent equality checks
        checks = [
            np.isclose(self.mass, other.mass),
            np.isclose(self.volume, other.volume)
        ]

        for name,component in self:
            checks.append(np.isclose(self[name].mass,other[name].mass))
            checks.append(np.isclose(self.mass_fraction[name],other.mass_fraction[name]))

        return all(checks)

    def all_components_have_mass(self):
        return all([component.has_mass for name, component in self])

    @property
    def mass(self):
        """Total mass of mixture."""
        return sum([component.mass for name,component in self])

    @mass.setter
    def mass(self,value):
        """Set total mass of mixture."""
        assert self.all_components_have_mass(), (f'Cannot set mass of solution with components lacking mass. Current '
                                                 'solution has: {k:v.mass for k,v in self.components.items()}')
        value = enforce_units(value,'mass')
        scale_factor = value/self.mass
        for name,component in self:
            component.mass = enforce_units((component.mass*scale_factor),'mass')
            
    def set_mass(self,value):
        """Setter for inline mass changes"""
        value = enforce_units(value,'mass')
        solution = self.copy()
        solution.mass = value
        return solution
            
    @property
    def volume(self):
        """Total volume of mixture. Only solvents are included in volume calculation"""
        volumes =[component.volume for name, component in self.solvents]
        if len(volumes)==0:
            return 0*units('ml')
        else:
            return sum(volumes)

    @volume.setter
    def volume(self,value):
        """Set total volume of mixture. Mass composition will be preserved"""
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
        """Setter for inline volume changes"""
        solution = self.copy()
        solution.volume = value
        return solution
        
    @property
    def solvent_sld(self):
        sld = []
        vfracs = []
        for name,vfrac in self.volume_fraction.items():
            component_sld = self.components[name].sld
            if component_sld is None:
                warnings.warn(f"SLD for solvent {name} is None. Check db",stacklevel=2)
                continue
            sld.append(component_sld)
            vfracs.append(vfrac)
        sld = [v*s/sum(vfracs) for v,s in zip(vfracs,sld)]
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
        """Mass fraction of components in mixture

        Returns
        -------
        mass_fraction: dict
        Component mass fractions
        """
        total_mass = self.mass
        mass_fraction = {}
        for name,component in self:
            mass_fraction[name] = component.mass/total_mass
        return {name:component.mass/total_mass for name,component in self}
    
    @mass_fraction.setter
    def mass_fraction(self,target_mass_fractions):
        """Mass fraction of components in mixture

        Returns
        -------
        mass_fraction: dict
        Component mass fractions
        """
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
        """Volume fraction of solvents in mixture

        Returns
        -------
        solvent_fraction: dict
        Component mass fractions
        """
        total_volume = self.volume
        return {name:component.volume/total_volume for name,component in self.solvents}
    
    @volume_fraction.setter
    def volume_fraction(self,vfrac_dict):
        """Volume fraction of components in mixture

        Returns
        -------
        volume_fraction: dict
        Component volume fractions
        """
        missing_comp = [name for name,component in self.solvents]
        for comp in vfrac_dict.keys():
            if comp in missing_comp:
                missing_comp.remove(comp)
        
        if len(missing_comp)>1:
            raise ValueError(f'Must specify at least {len(self.solvents)-1} volume fractions for mixture with {len(self.solvents)}')
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
            if component.has_formula:
                result[name] = enforce_units(component.moles/total_volume,'molarity')
        return result
    
    @molarity.setter
    def molarity(self,molarity_dict):
        total_volume = self.volume
        for name,molarity in molarity_dict.items():
            if not self.components[name].has_formula:
                raise ValueError(f'Attempting to set molarity of component without formula: {name}')
            else:
                molar_mass = self.components[name].formula.molecular_mass*AVOGADROS_NUMBER*units('g')
                self.components[name].mass = enforce_units(molarity*molar_mass*total_volume,'mass')
    
    def measure_out(self, amount: object, deplete: object = False) -> "Solution":
        """Create solution with identical composition at new total mass/volume"""
        
        if not has_units(amount):
            amount = units(amount)

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

