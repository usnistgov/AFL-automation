import copy
import itertools
import warnings
from typing import List, Optional, Dict, Set, Any

import numpy as np

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.mixing.Solution import Solution
from AFL.automation.shared.units import enforce_units

from scipy.optimize import lsq_linear, Bounds

def _extract_masses(solution: Solution,components: List[str],array: np.ndarray,unit: str='g') -> None:
    for i, component in enumerate(components):
        if solution.contains(component):
            array[i] =solution[component].mass.to(unit).magnitude
        else:
            array[i] = 0

def _extract_mass_fractions(stocks: List[Solution], components: List[str], matrix: np.ndarray) -> None:
    for i, component in enumerate(components):
        for j, stock in enumerate(stocks):
            if stock.contains(component):
                matrix[i, j] = stock.mass_fraction[component].to('').magnitude
            else:
                matrix[i, j] = 0

def _balance(mass_fraction_matrix: np.ndarray, target_masses: np.ndarray, bounds: Bounds, stocks: List[Solution]) -> \
List[Dict[Solution, str]]:
    """
    Calculate the mass transfers required to achieve the target masses.

    This method uses a least-squares linear solver to determine the base mass
    transfers needed to achieve the target masses. It then uses the `active_mask`
    from the solver's result to create other possible mass transfer scenarios by
    adjusting the transfers where the `active_mask` is -1, indicating that the solver
    bounded the solution using the pipette minimum.

    Parameters
    ----------
    target_masses : np.ndarray
        Array of target masses for each component.

    Returns
    -------
    List[Dict[Solution, str]]
        List of dictionaries where each dictionary represents a possible
        mass transfer scenario. The keys are stock solutions and the values
        are the masses to be transferred in grams.
    """

    result = lsq_linear(mass_fraction_matrix, target_masses, bounds=bounds)
    base_mass_transfer = {stock: f'{mass} g' for stock, mass in zip(stocks, result.x)}
    mass_transfers = [base_mass_transfer]
    negative_one_indices = [i for i, x in enumerate(result.active_mask) if x == -1]
    for combination in itertools.product(negative_one_indices):
        adjusted_transfer = base_mass_transfer.copy()
        for idx in combination:
            adjusted_transfer[stocks[idx]] = '0 g'
        mass_transfers.append(adjusted_transfer)

    return mass_transfers


def _make_balanced_target(mass_transfers, target):
    balanced_target = Solution(name="")
    balanced_target.protocol = []
    for stock, mass in mass_transfers.items():
        measured = stock.measure_out(mass)
        balanced_target = balanced_target + measured

        balanced_target.protocol.append(
            PipetteAction(
                source=stock.location,
                dest=target.location,
                volume=measured.volume.to('ul').magnitude,  # convert from ml for to ul
            )
        )
    # target name gets garbled by the __add__ step above
    balanced_target.name = target.name + "-balanced"
    # add any components that are in the target but that didn't end up in the stock
    for name, component in target:
        if not balanced_target.contains(name):
            balanced_target[name] = component.copy()
            balanced_target[name].mass = '0.0 g'
    return balanced_target


class MassBalance(Driver):
    defaults = {}
    defaults['minimum_volume'] = '20 ul'
    defaults['stocks'] = []
    defaults['targets'] = []

    def __init__(self,overrides=None):
        Driver.__init__(self, name='MassBalance', defaults=self.gather_defaults(), overrides=overrides)
        self.balanced = None
        self.minimum_transfer_volume = None
        self.bounds = None
        self.stocks = []
        self.stock_groups = [] #stock_groups is used for serial dilutions
        self.targets = []

        #self.minimum_volume = enforce_units(minimum_volume,'volume')

    @property
    def components(self) -> Set[str]:
        if not self.stocks:
            raise ValueError('No stocks have been added; Must call process_stocks before accessing components')
        return self.stock_components.union(self.target_components)

    @property
    def stock_components(self) -> Set[str]:
        if not self.stocks:
            raise ValueError('No stocks have been added; Must call process_stocks before accessing components')
        return {component for stocks,transfers in self.stock_groups for stock in stocks for component in stock.components}

    @property
    def target_components(self) -> Set[str]:
        if not self.targets:
            raise ValueError('No targets have been added; Must call process_stocks before accessing components')
        return {component for target in self.targets for component in target.components}

    def process_stocks(self):
        for stock_config in self.config['stocks']:
            stock = Solution(**stock_config)
            self.stocks.append(stock)
        self.stock_groups.append([self.stocks,[]])

    def process_targets(self):
        for target_config in self.config['targets']:
            target = Solution(**target_config)
            self.targets.append(target)

    def add_stock(self, solution: Dict, reset: bool = False):
        if reset:
            self.reset_stocks()
        self.config['stocks'] = self.config['stocks'] + [solution]

    def add_target(self, target: Dict, reset: bool =False):
        if reset:
            self.reset_targets()
        self.config['targets'] = self.config['targets'] + [target]

    def reset_stocks(self):
        self.config['stocks'] = []

    def reset_targets(self):
        self.config['targets'] = []

    def balance(self, tol: float = 1e-3):
        self.balanced = []
        self.process_stocks()
        self.process_targets()
        if any([stock.location is None for stock in self.stocks]):
            raise ValueError('Some stocks don\'t have a location specified. This should be specified when the stocks are instantiated')

        self.minimum_transfer_volume = enforce_units(self.config['minimum_transfer_volume'],'volume')
        self.bounds = Bounds(
            lb = [stock.measure_out(self.minimum_transfer_volume).mass.to('g').magnitude for stock in self.stocks],
            ub = [np.inf] * len(self.stocks),
            keep_feasible=False
        )

        components = list(self.components)
        target_masses = np.zeros(len(components))
        mass_fraction_matrix = np.zeros((len(components), len(self.stocks)))
        balanced_masses = np.zeros(len(components))

        for target in self.targets:
            mass_transfers = []
            for stocks,base_transfers in self.stock_groups:
                _extract_masses(target,components,array=target_masses)
                _extract_mass_fractions(stocks, components, matrix=mass_fraction_matrix)

                mass_transfers.append(_balance(mass_fraction_matrix, target_masses, self.bounds,stocks))
                if base_transfers:
                    mass_transfers[-1].insert(0,base_transfers)

            balanced_targets = []
            for i,transfers in enumerate(mass_transfers):
                balanced_target = _make_balanced_target(transfers, target)
                _extract_masses(balanced_target, components, array=balanced_masses)
                difference = (balanced_masses - target_masses)/target_masses
                if all(difference<tol):
                    balanced_targets.append([balanced_target, difference])

            if not balanced_targets:
                warnings.warn(f'No suitable mass balance found for {target.name}')
            else:
                balanced_target = min(balanced_targets,key=lambda x: sum(x[1]))
                self.balanced.append(balanced_target[0])












