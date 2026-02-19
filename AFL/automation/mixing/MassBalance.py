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
            balanced_target.components[name] = component.copy()
            balanced_target[name].mass = '0.0 g'
    return balanced_target


def _balance(mass_fraction_matrix: np.ndarray, target_masses: np.ndarray, bounds: Bounds, stocks: List[Solution], near_bound_tol: float = 0.1) -> List[Dict[Solution, str]]:
    result = lsq_linear(mass_fraction_matrix, target_masses, bounds=bounds)
    base_mass_transfer = {stock: f'{mass} g' for stock, mass in zip(stocks, result.x)}
    mass_transfers = [base_mass_transfer]

    # Identify stocks that the solver pushed to or near their lower bound.
    # These are candidates for exclusion (zeroing out) since the solver
    # wanted to use less than or close to the minimum transfer volume.
    # Using active_mask == -1 alone is insufficient: the solver may place
    # a stock slightly above its lower bound (e.g., to reduce H2O residual
    # from a mostly-water stock) even when the target calls for none of
    # that stock's solute.  A relative tolerance catches these cases.
    candidate_indices = [
        i for i in range(len(stocks))
        if result.active_mask[i] == -1
        or (bounds.lb[i] > 0 and result.x[i] <= bounds.lb[i] * (1 + near_bound_tol))
    ]

    # Try all subsets of candidate stocks and re-solve each
    # reduced problem so the remaining stocks are properly re-optimized.
    for r in range(1, len(candidate_indices) + 1):
        for combination in itertools.combinations(candidate_indices, r):
            exclude = set(combination)
            keep_indices = [i for i in range(len(stocks)) if i not in exclude]
            if not keep_indices:
                continue

            reduced_matrix = mass_fraction_matrix[:, keep_indices]
            reduced_bounds = Bounds(
                lb=[bounds.lb[i] for i in keep_indices],
                ub=[bounds.ub[i] for i in keep_indices],
                keep_feasible=False,
            )

            reduced_result = lsq_linear(reduced_matrix, target_masses, bounds=reduced_bounds)

            adjusted_transfer = {}
            reduced_idx = 0
            for i, stock in enumerate(stocks):
                if i in exclude:
                    adjusted_transfer[stock] = '0 g'
                else:
                    adjusted_transfer[stock] = f'{reduced_result.x[reduced_idx]} g'
                    reduced_idx += 1

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

    def balance_report(self):
        """
        Returns a json serializable structure that has all of the balanced targets
        that can be reconstituted by the user back into solution objects.
        """
        report = []
        for item in self.balanced:
            entry = {}
            if item['target']:
                entry['target'] = {
                    'name': item['target'].name,
                    'masses': {name: f"{c.mass.to('mg').magnitude} mg" for name, c in item['target']}
                }

            if item['balanced_target']:
                entry['balanced_target'] = {
                    'name': item['balanced_target'].name,
                    'masses': {name: f"{c.mass.to('mg').magnitude} mg" for name, c in item['balanced_target']}
                }
            else:
                entry['balanced_target'] = None

            if item['transfers']:
                entry['transfers'] = {stock.name: mass for stock, mass in item['transfers'].items()}
            else:
                entry['transfers'] = None

            if item.get('difference') is not None:
                entry['difference'] = item['difference'].tolist()
            else:
                entry['difference'] = None

            if item.get('success') is not None:
                entry['success'] = item['success']
            else:
                entry['success'] = None

            report.append(entry)
        return report

    def balance(self, tol=0.05, return_report=False):
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

                total_mass = sum(balanced_masses)
                total_target_mass = sum(target_masses)

                balanced_mass_fractions ={name:mass / total_mass for name, mass in zip(components, balanced_masses)}
                target_mass_fractions = {name:mass / total_target_mass for name, mass in zip(components, target_masses)}

                differences = []
                for name in components:
                    balanced_fraction = balanced_mass_fractions[name]
                    target_fraction = target_mass_fractions[name]

                    # Floor very small values to zero
                    if balanced_fraction < 1e-6:
                        balanced_fraction = 0.0
                    if target_fraction < 1e-6:
                        target_fraction = 0.0

                    if target_fraction == 0.0:
                        if balanced_fraction == 0.0:
                            difference = 0.0
                        else:
                            difference = balanced_fraction
                    else:
                        difference = (balanced_fraction - target_fraction) / target_fraction

                    differences.append(difference)

                differences = np.array(differences)

                success = all(np.abs(differences) < tol)

                balanced_targets.append({
                        'target':balanced_target,
                        'difference':differences,
                        'transfers':transfers,
                        'success':success,
                 })

            if not any(b['success'] for b in balanced_targets):
                warnings.warn(f'No suitable mass balance found for {target.name}\n')

            balanced_target = min(balanced_targets, key=lambda x: np.sum(np.abs(x['difference'])))
            self.balanced.append({
                'target':target,
                'balanced_target':balanced_target['target'],
                'transfers':balanced_target['transfers'],
                'difference': balanced_target['difference'],
                'success': balanced_target['success']
                })

        if return_report:
            return self.balance_report()


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
        MassBalanceBase.__init__(self)
        Driver.__init__(self, name='MassBalance', defaults=self.gather_defaults(), overrides=overrides)

        # Replace config with optimized settings for large stock configurations
        # This significantly improves performance when adding many stocks
        # Note: PersistentConfig will automatically load existing values from disk
        from AFL.automation.shared.PersistentConfig import PersistentConfig

        self.config = PersistentConfig(
            path=self.filepath,
            defaults=self.gather_defaults(),
            overrides=overrides,
            max_history=100,  # Reduced from default 10000 - large configs don't need that much history
            max_history_size_mb=50,  # Limit file size to 50MB
            write_debounce_seconds=0.5,  # Batch rapid stock additions (e.g., when adding many stocks)
            compact_json=True,  # Use compact JSON for large files
        )

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

    def add_targets(self, targets: List[Dict], reset: bool = False):
        if reset:
            self.reset_targets()
        self.config['targets'] = self.config['targets'] + targets
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

    def balance(self, return_report=False):
        self.process_stocks()
        self.process_targets()
        return super().balance(tol=self.config['tol'], return_report=return_report)


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

    
