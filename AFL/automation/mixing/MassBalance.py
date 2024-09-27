import numpy as np
from AFL.automation.mixing.Context import Context

from scipy.optimize import lsq_linear, Bounds

class MassBalance(Context):
    def __init__(self,name='MassBalance'):
        super().__init__(name=name)
        self.context_type = 'MassBalance'
        self.stocks = []
        self.targets = []
        self.protocols = []

    def __call__(self,reset=False,reset_stocks=False,reset_targets=False):
        if reset:
            self.stocks.clear()
        if reset_stocks:
            self.stocks.clear()
        if reset_targets:
            self.targets.clear()
        return self

    @property
    def components(self):
        return self.stock_components.union(self.target_components)

    @property
    def stock_components(self):
        return {component for stock in self.stocks for component in stock.components}

    @property
    def target_components(self):
        return {component for target in self.targets for component in target.components}

    @property
    def mass_fraction_matrix(self):
        components = list(self.components)
        matrix = np.zeros((len(components), len(self.stocks)))

        for i, component in enumerate(components):
            for j, stock in enumerate(self.stocks):
                if stock.contains(component):
                    matrix[i, j] = stock.mass_fractions[component].to('').magnitude
                else:
                    matrix[i, j] = 0

        return matrix

    @property
    def target_mass_vector(self):
        """This needs to support returning all targets at once"""
        components = list(self.components)
        vector = np.zeros(len(components))

        for i, component in enumerate(components):
            for target in self.targets:
                if target.contains(component):
                    vector[i] = target[component].mass.to('g').magnitude
                else:
                    vector[i] = 0

        return vector

    def balance(self):
        for stock in self.stocks:
            print(stock)
        # lbs, ubs = [], []
        # for stock in self.stocks:
        #     lb = (stock.measure_out('100 ul')).mass).to('g').magnitude
        #     ub = np.inf
        #     lbs.append(lb)
        #     ubs.append(ub)

        # bounds = Bounds(lb=lbs, ub=ubs, keep_feasible=False)
        # A = self.mass_fraction_matrix
        # for b in self.target_mass_vectors:
        #     b = self.mass_fraction_matrix
        #     scipy.optimize.lsq_linear(A, b, bounds=bounds)



