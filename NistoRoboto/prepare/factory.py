from itertools import product
import numpy as np
import periodictable

from NistoRoboto.prepare.Solution import Solution
from NistoRoboto.shared.units import units,has_units,is_mass,is_volume,is_molarity,is_concentration
from NistoRoboto.shared.utilities import listify


def HD2OFactory(name,phi_D2O=None,sld=None,properties=None):
    '''Create a list of H2O/D2O solutions'''
    solution_base = Solution(name,['H2O','D2O'])
    solution_base.set_properties_from_dict(properties)
    
    results = []
    if (phi_D2O is not None) and (sld is not None):
        raise ValueError('Can only specify phi_D2O OR sld')
    elif phi_D2O is not None:
        for vfrac in listify(phi_D2O):
            solution = solution_base.copy()
            solution.volume_fraction = {'D2O':vfrac}
            solution.name += f' D2O:{vfrac:4.3f}'
            results.append(solution)
    elif sld is not None:
        sldH = periodictable.formula('H2O@1n').neutron_sld(wavelength=5)[0]
        sldD = periodictable.formula('D2O@1n').neutron_sld(wavelength=5)[0]
        for s in listify(sld):
            solution = solution_base.copy()
            vfrac = (s-sldH)/(sldD-sldH)
            solution.volume_fraction = {'D2O':vfrac}
            solution.name += f' sld:{s:4.3f}'
            results.append(solution)
    else:
        raise ValueError('Must specify phi_D2O or sld')
    return results



def compositionSweepFactory(name,components,vary_components,lo,hi,num,logspace=False,properties=None):
    solution_base = Solution(name,components)
    solution_base.set_properties_from_dict(properties,inplace=True)
    
    lo = listify(lo)
    hi = listify(hi)
    num = listify(num)
    
    if (len(lo)==1) and (len(hi)==1) and (len(num)==1):
        lo *= len(vary_components)
        hi *= len(vary_components)
        num *= len(vary_components)
    elif not ((len(lo)==len(vary_components)) and (len(hi)==len(vary_components)) and (len(num)==len(vary_components))):
        raise ValueError('Poorly specified sweep. Number of lo/hi/num specs must be 1 or equal to the number of vary_components')
    
    params = []
    for l,h,n in zip(lo,hi,num):
        if not (has_units(l) and has_units(h)):
            raise ValueError('Lo and hi must have units')
        if logspace:
            params.append(np.geomspace(l,h,n))
        else:
            params.append(np.linspace(l,h,n))
    
    sweep = []
    for param in product(*params):
        solution = solution_base.copy()
        for i,value in enumerate(param):
            component = vary_components[i]
            solution.name += f' {component}:{value.magnitude:4.3f}'
            if is_mass(value):
                solution[component].mass = value
            elif is_volume(value):
                solution[component].volume = value
            elif is_concentration(value):
                solution.concentration = {component:value}
            elif is_molarity(value):
                solution.molarity = {component:value}
            else: #assume mass_fraction
                if solution.size>2:
                    raise ValueError('Variation by mass fraction only works for two component solutions')
                solution.mass_fraction = {component:value}
        sweep.append(solution)
    return sweep
                
    
            
    

