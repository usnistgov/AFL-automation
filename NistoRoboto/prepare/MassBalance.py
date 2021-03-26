import numpy as np
import scipy.optimize
import copy
from NistoRoboto.shared.units import units

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
        # mass_transfers,residuals,rank,singularity = np.linalg.lstsq(mass_fraction_matrix,target_component_masses,rcond=-1)
        mass_transfers,residuals = scipy.optimize.nnls(self.mass_fraction_matrix,self.target_component_masses)
        self.mass_transfers = {stock:(self.stock_location[stock],mass*units('g')) for stock,mass in zip(self.stocks,mass_transfers)}
        self.residuals = residuals


            

