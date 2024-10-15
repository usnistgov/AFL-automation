import copy
import itertools
import warnings
from typing import List, Optional, Dict, Set

import numpy as np

from AFL.automation.mixing.Context import Context
from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.mixing.Solution import Solution
from AFL.automation.shared.units import enforce_units

from scipy.optimize import lsq_linear, Bounds

def _extract_masses(solution: Solution,components: List[str],array: np.ndarray,unit: str='g') -> None:
    if array is None:
        array = np.zeros(len(components))
    for i, component in enumerate(components):
        if solution.contains(component):
            array[i] =solution[component].mass.to(unit).magnitude
        else:
            array[i] = 0


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


class MassBalanceLocal(Context):
    def __init__(self,name='MassBalance', minimum_volume='20 ul'):
        super().__init__(name=name)
        self.bounds = None
        self.mass_transfers = None
        self.context_type = 'MassBalance'
        self.stocks = []
        self.targets = []
        self.balanced = []

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
    def components(self) -> Set[str]:
        return self.stock_components.union(self.target_components)

    @property
    def stock_components(self) -> Set[str]:
        return {component for stock in self.stocks for component in stock.components}

    @property
    def target_components(self) -> Set[str]:
        return {component for target in self.targets for component in target.components}

    def mass_fraction_matrix(self) -> np.ndarray:
        components = list(self.components)
        matrix = np.zeros((len(components), len(self.stocks)))

        for i, component in enumerate(components):
            for j, stock in enumerate(self.stocks):
                if stock.contains(component):
                    matrix[i, j] = stock.mass_fraction[component].to('').magnitude
                else:
                    matrix[i, j] = 0

        return matrix



    def make_target_names(self,n_letters: int=2, components=None, name_map: Optional[Dict]=None):
        if components is None:
            components = self.components
        if name_map is None:
            name_map = {}

        for target in self.targets:
            name = ''
            for component in components:
                comp = name_map.get(component,component[:n_letters])
                name += f'{comp}{target.concentration[component].to("mg/ml").magnitude:.2f}'
            target.name = name + '-mgml'

    def balance(self,tol=0.05):
        if any([stock.location is None for stock in self.stocks]):
            raise ValueError('Some stocks don\'t have a location specified. This should be specified when the stocks are instantiated')

        self.bounds = Bounds(
            lb = [stock.measure_out(self.minimum_volume).mass.to('g').magnitude for stock in self.stocks],
            ub = [np.inf] * len(self.stocks),
            keep_feasible=False
        )

        components = list(self.components)
        target_masses = np.zeros(len(components))
        balanced_masses = np.zeros(len(components))
        for target in self.targets:
            _extract_masses(target,components,array=target_masses)

            mass_transfers = self._calculate_mass_transfers(target_masses)

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

    def _calculate_mass_transfers(self, target_masses: np.ndarray) -> List[Dict[Solution,str]]:
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

        result = lsq_linear(self.mass_fraction_matrix, target_masses, bounds=self.bounds)
        base_mass_transfer = {stock: f'{mass} g' for stock, mass in zip(self.stocks, result.x)}
        mass_transfers = [base_mass_transfer]
        negative_one_indices = [i for i, x in enumerate(result.active_mask) if x == -1]
        for combination in itertools.product(negative_one_indices):
            adjusted_transfer = base_mass_transfer.copy()
            for idx in combination:
                adjusted_transfer[self.stocks[idx]] = '0 g'
            mass_transfers.append(adjusted_transfer)

        return mass_transfers












