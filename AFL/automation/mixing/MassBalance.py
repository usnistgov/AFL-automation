import copy
import itertools
import warnings
from typing import List, Optional, Dict, Set, Any

import numpy as np
from scipy.optimize import lsq_linear, Bounds

from AFL.automation.mixing.Context import Context
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.shared.units import enforce_units

# --- Shared utility functions ---
def _extract_masses(solution: Solution, components: List[str], array: np.ndarray, unit: str = 'g') -> None:
    if array is None:
        array = np.zeros(len(components))
    for i, component in enumerate(components):
        if solution.contains(component):
            array[i] = solution[component].mass.to(unit).magnitude
        else:
            array[i] = 0


def _extract_mass_fractions(stocks: List[Solution], components: List[str], matrix: np.ndarray) -> None:
    for i, component in enumerate(components):
        for j, stock in enumerate(stocks):
            if stock.contains(component):
                matrix[i, j] = stock.mass_fraction[component].to('').magnitude
            else:
                matrix[i, j] = 0

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
                volume=measured.volume.to('ul').magnitude,
            )
        )
    balanced_target.name = target.name + "-balanced"
    for name, component in target:
        if not balanced_target.contains(name):
            balanced_target[name] = component.copy()
            balanced_target[name].mass = '0.0 g'
    return balanced_target


def _balance(mass_fraction_matrix: np.ndarray, target_masses: np.ndarray, bounds: Bounds, stocks: List[Solution]) -> List[Dict[Solution, str]]:
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

# --- MassBalance Base Class ---
class MassBalanceBase:
    def __init__(self):
        self.balanced = []
        self.bounds = None

    @property
    def components(self) -> Set[str]:
        return self.stock_components.union(self.target_components)

    @property
    def stock_components(self) -> Set[str]:
        raise NotImplementedError

    @property
    def target_components(self) -> Set[str]:
        raise NotImplementedError

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

    def make_target_names(self, n_letters: int = 2, components=None, name_map: Optional[Dict] = None):
        if components is None:
            components = self.components
        if name_map is None:
            name_map = {}
        for target in self.targets:
            name = ''
            for component in components:
                comp = name_map.get(component, component[:n_letters])
                name += f'{comp}{target.concentration[component].to("mg/ml").magnitude:.2f}'
            target.name = name + '-mgml'

    def balance(self, tol=0.05):
        if any([stock.location is None for stock in self.stocks]):
            raise ValueError("Some stocks don't have a location specified. This should be specified when the stocks are instantiated")
        self._set_bounds()
        components = list(self.components)
        target_masses = np.zeros(len(components))
        balanced_masses = np.zeros(len(components))
        self.balanced = []
        for target in self.targets:
            _extract_masses(target, components, array=target_masses)
            mass_transfers = _balance(self.mass_fraction_matrix(), target_masses, self.bounds, self.stocks)
            balanced_targets = []
            for transfers in mass_transfers:
                balanced_target = _make_balanced_target(transfers, target)
                _extract_masses(balanced_target, components, array=balanced_masses)
                difference = (balanced_masses - target_masses) / target_masses
                if all(difference < tol):
                    balanced_targets.append({
                        'target':balanced_target, 
                        'difference':difference,
                        'transfers':transfers,
                    })
            if not balanced_targets:
                warnings.warn(f'No suitable mass balance found for {target.name}')
                self.balanced.append({
                    'target':target, 
                    'balanced_target':None, 
                    'transfers':None,
                    })
            else:
                balanced_target = min(balanced_targets, key=lambda x: sum(x['difference']))
                self.balanced.append({
                    'target':target, 
                    'balanced_target':balanced_target['target'], 
                    'transfers':balanced_target['transfers'],
                    })


    def _set_bounds(self):
        raise NotImplementedError


# --- MassBalanceContext ---
class MassBalance(MassBalanceBase, Context):
    def __init__(self, name='MassBalance', minimum_volume='20 ul'):
        Context.__init__(self, name=name)
        MassBalanceBase.__init__(self)
        self.context_type = 'MassBalance'
        self.stocks = []
        self.targets = []
        self.minimum_volume = enforce_units(minimum_volume, 'volume')
        self.config = {'stocks': [], 'targets': [], 'minimum_volume': minimum_volume}

    def __call__(self, reset=False, reset_stocks=False, reset_targets=False):
        if reset or reset_stocks:
            self.stocks.clear()
        if reset or reset_targets:
            self.targets.clear()
        return self

    @property
    def stock_components(self) -> Set[str]:
        return {component for stock in self.stocks for component in stock.components}

    @property
    def target_components(self) -> Set[str]:
        return {component for target in self.targets for component in target.components}

    def _set_bounds(self):
        self.bounds = Bounds(
            lb=[stock.measure_out(self.minimum_volume).mass.to('g').magnitude for stock in self.stocks],
            ub=[np.inf] * len(self.stocks),
            keep_feasible=False
        )


# --- MassBalanceDriver ---
class MassBalanceDriver(MassBalanceBase, Driver):
    defaults = {'minimum_volume': '20 ul', 'stocks': [], 'targets': [], 'tol': 1e-3}


    def __init__(self, overrides=None):
        MassBalance.__init__(self)
        Driver.__init__(self, name='MassBalance', defaults=self.gather_defaults(), overrides=overrides)
        self.minimum_transfer_volume = None
        self.stocks = []
        self.targets = []
        try:
            self.mixdb = MixDB.get_db()
        except ValueError:
            self.mixdb = MixDB()
        self.useful_links['Edit Components DB'] = 'static/components.html'
        self.useful_links['Configure Stocks'] = 'static/stocks.html'
        try:
            self.process_stocks()
        except Exception as e:
            warnings.warn(f'Failed to load stocks from config: {e}', stacklevel=2)

    @property
    def stock_components(self) -> Set[str]:
        if not self.stocks:
            raise ValueError('No stocks have been added; Must call process_stocks before accessing components')
        return {component for stock in self.stocks for component in stock.components}

    @property
    def target_components(self) -> Set[str]:
        if not self.targets:
            raise ValueError('No targets have been added; Must call process_stocks before accessing components')
        return {component for target in self.targets for component in target.components}

    def process_stocks(self):
        new_stocks = []
        for stock_config in self.config['stocks']:
            stock = Solution(**stock_config)
            new_stocks.append(stock)
            if 'stock_locations' in self.config and stock.location is not None:
                self.config['stock_locations'][stock.name] = stock.location
        self.stocks = new_stocks

    def process_targets(self):
        self.targets = []
        for target_config in self.config['targets']:
            target = Solution(**target_config)
            self.targets.append(target)

    def add_stock(self, solution: Dict, reset: bool = False):
        if reset:
            prev = []
            self.reset_stocks()
        else:
            prev = list(self.config['stocks'])
        self.config['stocks'] = self.config['stocks'] + [solution]
        if 'stock_locations' in self.config and solution.get('location') is not None:
            self.config['stock_locations'][solution['name']] = solution['location']
        try:
            self.process_stocks()
        except Exception as e:
            self.config['stocks'] = prev
            self.process_stocks()
            raise e
        self.config._update_history()

    def add_target(self, target: Dict, reset: bool = False):
        if reset:
            self.reset_targets()
        self.config['targets'] = self.config['targets'] + [target]
        self.config._update_history()

    def reset_stocks(self):
        self.config['stocks'] = []
        if 'stock_locations' in self.config:
            self.config['stock_locations'].clear()
        self.config._update_history()

    def reset_targets(self):
        self.config['targets'] = []
        self.config._update_history()

    @Driver.unqueued()
    def list_stocks(self):
        self.process_stocks()
        out = []
        for stock in self.stocks:
            data = stock.to_dict()
            data['location'] = stock.location
            out.append(data)
        return out

    def _set_bounds(self):
        self.minimum_transfer_volume = enforce_units(self.config['minimum_volume'], 'volume')
        self.bounds = Bounds(
            lb=[stock.measure_out(self.minimum_transfer_volume).mass.to('g').magnitude for stock in self.stocks],
            ub=[np.inf] * len(self.stocks),
            keep_feasible=False
        )
    
    def balance(self):
        self.process_stocks()
        self.process_targets()
        super().balance(tol=self.config['tol'])

    # --- Component database management ---

    @Driver.unqueued()
    def list_components(self):
        return self.mixdb.list_components()

    @Driver.unqueued()
    def add_component(self, **component):
        uid = self.mixdb.add_component(component)
        self.mixdb.write()
        return uid

    @Driver.unqueued()
    def update_component(self, **component):
        uid = self.mixdb.update_component(component)
        self.mixdb.write()
        return uid

    @Driver.unqueued()
    def remove_component(self, name=None, uid=None):
        self.mixdb.remove_component(name=name, uid=uid)
        self.mixdb.write()
        return 'OK'


    
