import numpy as np
import warnings
try:
    import scipy.optimize
    import scipy.spatial
except ModuleNotFoundError:
    warnings.warn('Import of SciPy failed; this is expected on OT-2, worrying on other platforms.  Mass balance solves will not work.  Please, install scipy if able.',stacklevel=2)
import pandas as pd
import xarray as xr
import copy
from AFL.automation.shared.units import units
from AFL.automation.prepare import Solution

try:
    import AFL.agent.PhaseMap
    from AFL.agent.PhaseMap import to_xy
except ImportError:
    warnings.warn('Cannot import AFL agent tools. Some features of Massbalance will not work correctly')

try:
    from tqdm.contrib.itertools import product
except ImportError:
    from itertools import product

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
                    row.append(stock.mass_fraction[name])
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

    def sample_composition_space(self,pipette_min=5*units('ul'),grid_density=5):
        '''Combine stock solutions to generate samples of possible target compositions'''
        if self.components is None:
            self.process_components()
            
        masses = []
        fraction_grid=[]
        for stock in self.stocks:
            row = []
            ratio = (pipette_min/stock.volume).to_base_units().magnitude
            fraction_grid.append(list(np.linspace(ratio,1.0,grid_density)))
            for component in self.components:
                if component in stock.components:
                    row.append(stock[component].mass.to('mg').magnitude)
                else:
                    row.append(0)
            masses.append(row)
        masses = np.array(masses)
        
        stock_samples = []#list of possible stock combinations
        stock_fractions = []
        for fractions in product(*fraction_grid):
            stock_fractions.append(fractions)
            mass = (masses.T*fractions).sum(1)
            mass = mass/mass.sum()
            stock_samples.append(mass)
        self.stock_samples = pd.DataFrame(stock_samples,columns=self.components)
        self.stock_samples_fractions = stock_fractions
        return self.stock_samples
    
    def calculate_bounds(self,components=None,exclude_comps_below=None,fixed_comps=None,make_phasemap=True):
        
        if self.stock_samples is None:
            raise ValueError('Must call .sample_composition_space before calculating bounds')
        
        if components is None:
            components= self.components
            
        if len(components)==3:
            comps = self.stock_samples[list(components)].values
            comps = comps/comps.sum(1)[:,np.newaxis]#normalize to 1.0 basis
            if exclude_comps_below is not None:
                mask = ~((comps<exclude_comps_below).any(1))
                comps = comps[mask]
            xy = to_xy(comps)
        elif len(components)==2:
            xy = self.stock_samples[list(components)]
            mask = slice(None)
        else:
            raise ValueError(f"Bounds can only be calculated in two or three dimensions. You specified: {components}")
        
        self.stock_samples_xy = xy
        self.stock_samples_mask = mask
        if make_phasemap:
            phasemap = xr.Dataset()
            for component in list(components):
                phasemap[component]=self.stock_samples[component].iloc[mask]
            self.stock_samples_phasemap = phasemap
        self.stock_samples_hull = scipy.spatial.ConvexHull(xy)
        self.stock_samples_delaunay = scipy.spatial.Delaunay(xy)
    
    def in_bounds(self,points):
        
        if self.stock_samples_delaunay is None:
            raise ValueError('Must call sample_composition_space and calculate_bounds before calling in_bounds')
        
        if points.shape[1]==3:
            p = to_xy(points)
        elif points.shape[1]==2:
            p = points
        else:
            raise ValueError('Can only pass two or three dimensional data to in_bounds')
                             
        return self.stock_samples_delaunay.find_simplex(p)>=0
    
    def plot_bounds(self,include_points):
        import matplotlib.pyplot as plt
        if include_points:
            ax = self.stock_samples_phasemap.afl.comp.plot_discrete()
        else:
            fig,ax = plt.subplots(1,1)
        
        for simplex in self.stock_samples_hull.simplices:
            ax.plot(self.stock_samples_xy[simplex, 0], self.stock_samples_xy[simplex, 1], 'g:')
