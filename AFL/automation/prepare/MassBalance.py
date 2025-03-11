import numpy as np
import warnings
try:
    import scipy.optimize
    import scipy.spatial
except ModuleNotFoundError:
    warnings.warn('Import of SciPy failed; this is expected on OT-2, worrying on other platforms.  Mass balance solves will not work.  Please, install scipy if able.',stacklevel=2)
import pandas as pd
import copy
from AFL.automation.shared.units import units,is_concentration,get_unit_type
from AFL.automation.prepare import Solution
from AFL.automation import prepare 
from collections import defaultdict

try:
    import xarray as xr
except ImportError:
    warnings.warn('Cannot import xarray...some features will not work correctly.')

try:
    import AFL.agent.PhaseMap
    from AFL.agent.util import ternary_to_xy
except ImportError:
    warnings.warn('Cannot import AFL agent tools. Some features of Massbalance will not work correctly')

try:
    from tqdm.contrib.itertools import product
    from tqdm import tqdm
except ImportError:
    from itertools import product
    tqdm = lambda x: x

class MassBalance:
    def __init__(self):
        self.reset()

    def copy(self):
        return copy.deepcopy(self)
        
    def add_stock(self,stock,location):
        stock = stock.copy()
        self.stocks.append(stock)
        self.stock_location[stock] = location
            
    def set_target(self,target,location):
        target = target.copy()
        self.target = target
        self.target_location = location
        
    def reset_targets(self):
        self.targets = []
        self.target_location = {}
            
    def reset_stocks(self):
        self.stocks = []
        self.stock_location = {}

    def reset(self):
        self.mass_fraction_matrix    = None
        self.target_component_masses = None
        self.components        = set()
        self.target_components = set()
        self.stock_components  = set()
        self.reset_stocks()
        self.reset_targets()

    def process_components(self):
        self.components        = []
        self.target_components = []
        self.stock_components  = []

        for target in self.targets:
            for name,component in target:
                if name not in self.components:
                    self.components.append(name)
                if name not in self.target_components:
                    self.target_components.append(name)

        for stock in self.stocks:
            for name,component in stock:
                if name not in self.components:
                    self.components.append(name)
                if name not in self.stock_components:
                    self.stock_components.append(name)

    def make_mass_fraction_matrix(self):

        # build matrix and vector representing mass balance
        mass_fraction_matrix = []
        for name in self.components:
            row = []
            for stock in self.stocks:
                if stock.contains(name):
                    row.append(stock.mass_fraction[name].to('').magnitude)
                else:
                    row.append(0)
            mass_fraction_matrix.append(row)
        self.mass_fraction_matrix = mass_fraction_matrix
        return mass_fraction_matrix
            
    def make_target_component_masses(self):
        # build matrix and vector representing mass balance
        target_component_masses = []
        for name in self.components:
            if self.target.contains(name):
                target_component_masses.append(self.target[name].mass.to('g').magnitude)
            else:
                target_component_masses.append(0)
        self.target_component_masses = target_component_masses
        return target_component_masses 

    def balance_mass(self):
        self.process_components()

        self.mass_fraction_matrix = self.make_mass_fraction_matrix()
        self.target_component_masses = self.make_target_component_masses()

        #solve mass balance 
        #mass_transfers,residuals,rank,singularity = np.linalg.lstsq(self.mass_fraction_matrix,self.target_component_masses,rcond=-1)
        mass_transfers,residuals = scipy.optimize.nnls(self.mass_fraction_matrix,self.target_component_masses)
        self.mass_transfers = {stock:(self.stock_location[stock],mass*units('g')) for stock,mass in zip(self.stocks,mass_transfers)}
        self.residuals = residuals

    def sample_composition_space(self,pipette_min=5*units('ul'),stock_transfer_max=3500*units('ul'),grid_density=5,composition_data='frac'):
        '''Combine stock solutions to generate samples of possible target compositions'''
        if self.components is None:
            self.process_components()
            
        density = []
        for component_name in self.components:
            component = prepare.db[component_name]
            if component.is_solute:
                density.append(0)
            else:
                density.append(component.density.to('mg/ml').magnitude)
        density = np.array(density)
            
        stock_mass_fractions = []#mass matrix of each component in each stock
        mass_grid=[]
        for stock in self.stocks:
            row = []
            density_row = []
            ratio = (pipette_min/stock.volume).to_base_units().magnitude
            
            s1 = stock.copy()
            s1.volume = pipette_min
            stock_mass_min = s1.mass.to('mg').magnitude
            
            s2 = stock.copy()
            s2.volume = stock_transfer_max
            stock_mass_max = s2.mass.to('mg').magnitude
            
            l1 = list(np.linspace(stock_mass_min,stock_mass_max,grid_density))
            l2 = list(np.geomspace(stock_mass_min,stock_mass_max,grid_density))
            l = list(np.unique(l1+l2))
            mass_grid.append(l)
            for component in self.components:
                if component in stock.components:
                    row.append(stock.mass_fraction[component].to('').magnitude)
                else:
                    row.append(0)
            stock_mass_fractions.append(row)
        stock_mass_fractions = np.array(stock_mass_fractions)
        
        stock_samples_conc = []
        stock_samples_mass = []
        stock_samples_volume = []
        stock_samples_frac = []
        stock_mass_transfers = []
        for masses in product(*mass_grid):
            stock_mass_transfers.append(masses)
            mass = (stock_mass_fractions.T*masses).sum(1)
            mass_frac = mass/mass.sum()
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                volume = mass/density
            volume = volume[~np.isinf(volume)].sum()
            
            conc = mass/volume
            
            stock_samples_mass.append(mass)
            stock_samples_frac.append(mass_frac)
            stock_samples_volume.append(volume)
            stock_samples_conc.append(conc)
        self.mass_grid = mass_grid
        self.stock_mass_fractions = stock_mass_fractions
        self.stock_samples = xr.Dataset()
        self.stock_samples['samples_frac'] = xr.DataArray(stock_samples_frac,dims=['sample','component'],coords={'component':self.components})
        self.stock_samples['samples_mass'] = xr.DataArray(stock_samples_mass,dims=['sample','component'],coords={'component':self.components},attrs={'units':'mg'})
        self.stock_samples['samples_conc'] = xr.DataArray(stock_samples_conc,dims=['sample','component'],coords={'component':self.components},attrs={'units':'mg/ml'})
        self.stock_samples['samples_volume'] = xr.DataArray(stock_samples_volume,dims=['sample'],attrs={'units':'ml'})
        self.stock_samples['stock_mass_transfers'] = (('sample','stock'),stock_mass_transfers)
        self.stock_samples['stock'] = list([i.name for i in self.stocks])
        
        #need composition arrays as individual dataarrays in the dataset
        if composition_data=='frac':
            self.stock_samples.update(self.stock_samples.samples_frac.to_dataset('component'))
        elif composition_data=='conc':
            self.stock_samples.update(self.stock_samples.samples_conc.to_dataset('component'))
        elif composition_data=='mass':
            self.stock_samples.update(self.stock_samples.samples_mass.to_dataset('component'))
            
        return self.stock_samples
    
    
    def constrain_samples_conc(self,constraints,rtol=0.05):
        processed_constraints = {}
        for name,con in constraints.items():
            if is_concentration(con['value']):
                processed_constraints[name] = {'value':con['value'].to('mg/ml').magnitude,'compare':con['compare']}
            else:
                raise ValueError(f'This method only works with concentration constraints. You passed {get_unit_type(con["value"])}')
    
        masks = []
        for name,con in processed_constraints.items():
            sample_concs = self.stock_samples.samples_conc.sel(component=name)
            if con['compare'] in ('==','eq','equal','equals'):
                mask = np.isclose(sample_concs,con['value'],atol=0.0,rtol=rtol)
            elif con['compare'] in ('<','lt','lessthan','less than'):
                mask = np.less(sample_concs,con['value'])
            elif con['compare'] in ('>','gt','greaterthan','greater than'):
                mask = np.greater(sample_concs,con['value'])
            masks.append(mask)
            
        self.stock_samples['constraint_mask'] = ('sample',np.all(masks,axis=0))
        self.stock_samples_all = self.stock_samples.copy()
        self.stock_samples = self.stock_samples.where(self.stock_samples['constraint_mask'],drop=True)
        return self.stock_samples
    
    
    def calculate_bounds(self,components=None,exclude_comps_below=None,fixed_comps=None,composition_data='samples_frac',ternary=True):
        
        if self.stock_samples is None:
            raise ValueError('Must call .sample_composition_space before calculating bounds')
        
        if components is None:
            components= self.components

        self.stock_samples.attrs['components'] = components
            
        if (len(components)==3) and ternary:
            comps = self.stock_samples[composition_data].sel(component=components)
            comps = comps/comps.sum('component')#[:,np.newaxis]#normalize to 1.0 basis
            if exclude_comps_below is not None:
                mask = ~((comps<exclude_comps_below).any('component'))
                comps = comps[mask]
            else:
                mask = xr.ones_like(self.stock_samples[composition_data],dtype=bool)
            xy = ternary_to_xy(comps.values)
        else:
            comps = self.stock_samples[composition_data].sel(component=components)
            mask = comps.isel(component=0).copy(data=np.ones(comps.values.shape[0],dtype=bool)).reset_coords(drop=True)
            xy = comps.values
        
        
        #need to remove anything associated with sample_valid coordinate
        self.stock_samples = self.stock_samples.drop_vars(['xy','samples_valid'],errors='ignore')
        
        self.stock_samples['xy'] = (('sample_valid','coord'),xy)
        self.stock_samples['samples_valid']  = (('sample_valid','component'),self.stock_samples[composition_data].where(mask,drop=True).data)
        self.stock_samples.attrs['hull']= scipy.spatial.ConvexHull(xy)
        self.stock_samples.attrs['delaunay'] = scipy.spatial.Delaunay(xy)
    
    def in_bounds(self,points,ternary=True):
        if not hasattr(self,'stock_samples'):
            raise ValueError('You must call .sample_composition_space and .calculate_bounds with before calling this method')
     
        if (points.shape[1]==3) and ternary:
            p = ternary_to_xy(points)
        else:
            p = points
        #else:
            #raise ValueError('Can only pass two or three dimensional data to in_bounds')
                             
        return self.stock_samples.attrs['delaunay'].find_simplex(p)>=0


    def make_grid_mask(self,pts_per_row=100,ternary=True):
        if not hasattr(self,'stock_samples'):
            raise ValueError('You must call .sample_composition_space and .calculate_bounds with before calling this method')

        if 'grid' in self.stock_samples:
            self.stock_samples = self.stock_samples.drop_dims('grid')
        self.stock_samples.afl.comp.add_grid(self.stock_samples.attrs['components'],pts_per_row=pts_per_row,overwrite=True)
        
        mask = self.in_bounds(self.stock_samples.afl.comp.get_grid().values,ternary=ternary)
        self.stock_samples['grid_mask'] = ('grid',mask)
        self.stock_samples = self.stock_samples.set_index(grid=self.stock_samples.attrs['components_grid'])
        return self.stock_samples

    def plot_grid_mask(self):
        if not hasattr(self,'stock_samples'):
            raise ValueError('You must call .make_grid_mask before calling this method')
        self.stock_samples.afl.comp.plot_discrete(self.stock_samples.attrs['components_grid'],labels='grid_mask',marker='.',s=1)
        self.stock_samples.where(self.stock_samples.grid_mask,drop=True).afl.comp.plot_discrete(self.stock_samples.attrs['components_grid'],labels='mask',marker='.',s=1)
    
    def plot_bounds(self,include_points=True):
        import matplotlib.pyplot as plt

        fig,ax = plt.subplots(1,1)

        if include_points:
            plt.scatter(*self.stock_samples.xy.values.T,s=1)
        
        for simplex in self.stock_samples.attrs['hull'].simplices:
            ax.plot(self.stock_samples.xy[simplex, 0], self.stock_samples.xy[simplex, 1], 'g:')
        AFL.agent.PhaseMap.format_ternary(ax,*self.stock_samples.attrs['components'])
