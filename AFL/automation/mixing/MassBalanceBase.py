import itertools
import warnings
from typing import List, Optional, Dict, Set

import numpy as np
from scipy.optimize import lsq_linear, Bounds

from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.mixing.Solution import Solution


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

                total_target_mass = sum(target_masses)

                # Compute per-component relative differences using absolute
                # masses so that total-mass deviations are detected.  Handle
                # zero target masses gracefully to avoid division by zero.
                differences = np.zeros(len(components))
                for i in range(len(components)):
                    t = target_masses[i]
                    b = balanced_masses[i]
                    if t == 0 and b == 0:
                        differences[i] = 0.0
                    elif t == 0:
                        # Target is zero but balanced is not; express the
                        # mismatch relative to the total target mass so the
                        # tolerance comparison remains meaningful.
                        if total_target_mass > 0:
                            differences[i] = b / total_target_mass
                        else:
                            differences[i] = 1.0
                    else:
                        differences[i] = abs(b - t) / t

                success = all(np.abs(differences) < tol)

                balanced_targets.append({
                        'target':balanced_target,
                        'difference':differences,
                        'transfers':transfers,
                        'success':success,
                 })

            if not any(b['success'] for b in balanced_targets):
                warnings.warn(f'No suitable mass balance found for {target.name}\n')
                self.balanced.append({
                    'target':target,
                    'balanced_target':None,
                    'transfers':None,
                    'difference': None,
                    'success': False,
                    })
            else:
                successful_targets = [b for b in balanced_targets if b['success']]
                balanced_target = min(successful_targets, key=lambda x: np.sum(np.abs(x['difference'])))
                self.balanced.append({
                    'target':target,
                    'balanced_target':balanced_target['target'],
                    'transfers':balanced_target['transfers'],
                    'difference': balanced_target['difference'],
                    'success': balanced_target['success'],
                    })

        if return_report:
            return self.balance_report()


    def _set_bounds(self):
        raise NotImplementedError
