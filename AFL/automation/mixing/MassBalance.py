import numpy as np

from AFL.automation.mixing.Context import Context
from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.shared.units import enforce_units,units

from scipy.optimize import lsq_linear, Bounds


def _extract_masses(solution,components,array=None,unit='g'):
    if array is None:
        array = np.zeros(len(components))
    for i, component in enumerate(components):
        if solution.contains(component):
            array[i] =solution[component].mass.to(unit).magnitude
        else:
            array[i] = 0
    return array


class MassBalance(Context):
    def __init__(self,name='MassBalance', minimum_volume='20 ul'):
        super().__init__(name=name)
        self.mass_transfers = None
        self.context_type = 'MassBalance'
        self.stocks = []
        self.targets = []
        self.balanced_targets = []
        self.protocols = []

        self.minimum_volume = enforce_units(minimum_volume,'volume')

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

    def balance(self,tol=0.05):
        lower_bounds = [stock.measure_out(self.minimum_volume).mass.to('g').magnitude for stock in self.stocks]
        upper_bounds = [np.inf]*len(self.stocks)
        bounds = Bounds(
            lb=lower_bounds,
            ub=upper_bounds,
            keep_feasible=False
        )

        if any([stock.location is None for stock in self.stocks]):
            raise ValueError('Some stocks don\'t have a location specified. This should be specified when the stocks are instantiated')

        mass_fraction_matrix = self.mass_fraction_matrix
        components = list(self.components)
        target_masses = np.zeros(len(components))
        self.mass_transfers = []
        for target in self.targets:
            target_masses = _extract_masses(target,components,array=target_masses)

            result = lsq_linear(mass_fraction_matrix, target_masses, bounds=bounds)
            mass_transfers = {stock: mass * units('g') for stock, mass in zip(self.stocks, result.x)}
            self.mass_transfers.append(mass_transfers)

            protocol = []
            for stock, mass in mass_transfers.items():
                measured = stock.measure_out(mass)

                action = PipetteAction(
                    source=stock.location,
                    dest=target.location,
                    volume=measured.volume.to('ul').magnitude,  # convet from ml for to ul
                )
                protocol.append(action)
            self.protocols.append(protocol)

            # validate

            # difference = (masses - target_masses)/target_masses
            # if any(difference<tol):
            #     balanced_target = target.copy()
            #     for name,mass in zip(components,masses):
            #         balanced_target[name]._mass = mass*units.g
            #     self.balanced_targets.append(balanced_target)

        return protocol

    def make_solution_from_protocol(self, protocol):
        target_check = Solution('target_check', components=[])
        for stock, (stock_loc, mass) in self.balancer.mass_transfers.items():
            if mass > self.mass_cutoff:  # tolerance
                removed = stock.copy()
                removed.mass = mass

                ##if this is changed, make_protocol needs to be updated
                if (removed.volume > 0) and (removed.volume < self.volume_cutoff):
                    continue

                target_check = target_check + removed

        # need to add empty components for equality check
        for name, component in target:
            if not target_check.contains(name):
                c = component.copy()
                c._mass = 0.0 * units('g')
                target_check = target_check + c











