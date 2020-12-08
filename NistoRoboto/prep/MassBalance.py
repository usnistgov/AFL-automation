import numpy as np
import scipy.optimize

class MassBalance:
    def __init__(self):
        self.reset()
        
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
        self.reset_stocks()
        self.reset_targets()

    def process_components(self):
        self.components        = set()
        self.target_components = set()
        self.stock_components  = set()

        for target in self.targets:
            for name,component in target:
                if not component._has_mass:
                    raise ValueError(f'Cannot do mass balance without masses specified. \nComponent {name} in target {target} has no mass!')
                self.components.add(name)
                self.target_components.add(name)

        for stock in self.stocks:
            for name,component in stock:
                if not component._has_mass:
                    raise ValueError(f'Cannot do mass balance without masses specified. \nComponent {name} in stock {stock} has no mass!')
                self.components.add(name)
                self.stock_components.add(name)



    def mass_balance(self):
        self.process_components()

        # build matrix and vector representing mass balance
        mass_fraction_matrix = []
        target_component_masses = []
        for name in self.components:
            row = []
            for stock in self.stocks:
                if stock.contains(name):
                    row.append(stock.mass_fraction[name].magnitude)
                else:
                    row.append(0)
            mass_fraction_matrix.append(row)
            
            if self.target.contains(name):
                target_component_masses.append(self.target[name].mass.to('g').magnitude)
            else:
                target_component_masses.append(0)
        self.mass_fraction_matrix = mass_fraction_matrix
        self.target_component_masses = target_component_masses

        #solve mass balance 
        # mass_transfers,residuals,rank,singularity = np.linalg.lstsq(mass_fraction_matrix,target_component_masses,rcond=-1)
        mass_transfers,residuals = scipy.optimize.nnls(self.mass_fraction_matrix,self.target_component_masses)
        self.mass_transfers = mass_transfers
        self.residuals = residuals


            

