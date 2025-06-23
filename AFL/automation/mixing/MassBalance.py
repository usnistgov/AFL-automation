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
from AFL.automation.shared.units import enforce_units


# --- Shared utility functions ---
def _extract_masses(
    solution: Solution, components: List[str], array: np.ndarray, unit: str = "g"
) -> None:
    if array is None:
        array = np.zeros(len(components))
    for i, component in enumerate(components):
        if solution.contains(component):
            array[i] = solution[component].mass.to(unit).magnitude
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
                volume=measured.volume.to("ul").magnitude,
            )
        )
    balanced_target.name = target.name + "-balanced"
    for name, component in target:
        if not balanced_target.contains(name):
            balanced_target[name] = component.copy()
            balanced_target[name].mass = "0.0 g"
    return balanced_target


def _balance(
    mass_fraction_matrix: np.ndarray,
    target_masses: np.ndarray,
    bounds: Bounds,
    stocks: List[Solution],
) -> List[Dict[Solution, str]]:
    result = lsq_linear(mass_fraction_matrix, target_masses, bounds=bounds)
    base_mass_transfer = {stock: f"{mass} g" for stock, mass in zip(stocks, result.x)}
    mass_transfers = [base_mass_transfer]
    negative_one_indices = [i for i, x in enumerate(result.active_mask) if x == -1]
    for combination in itertools.product(negative_one_indices):
        adjusted_transfer = base_mass_transfer.copy()
        for idx in combination:
            adjusted_transfer[stocks[idx]] = "0 g"
        mass_transfers.append(adjusted_transfer)
    return mass_transfers


# --- MassBalance Base Class ---
class MassBalanceBase:
    def __init__(self):
        self.balanced = []
        self.bounds = None

    def _stock_objs(self) -> List[Solution]:
        """Return stock definitions as :class:`Solution` objects."""
        objs = []
        for stock in self.config.get("stocks", []):
            if isinstance(stock, Solution):
                objs.append(stock)
            else:
                objs.append(Solution(**stock))
        return objs

    @property
    def components(self) -> Set[str]:
        return self.stock_components.union(self.target_components)

    @property
    def stock_components(self) -> Set[str]:
        raise NotImplementedError

    @property
    def target_components(self) -> Set[str]:
        raise NotImplementedError

    def mass_fraction_matrix(
        self, stocks: Optional[List[Solution]] = None
    ) -> np.ndarray:
        """Return a matrix of component mass fractions for each stock."""
        if stocks is None:
            stocks = self._stock_objs()
        components = list(self.components)
        matrix = np.zeros((len(components), len(stocks)))
        for i, component in enumerate(components):
            for j, stock in enumerate(stocks):
                if stock.contains(component):
                    matrix[i, j] = stock.mass_fraction[component].to("").magnitude
                else:
                    matrix[i, j] = 0
        return matrix

    def make_target_names(
        self, n_letters: int = 2, components=None, name_map: Optional[Dict] = None
    ):
        if components is None:
            components = self.components
        if name_map is None:
            name_map = {}
        for target in self.targets:
            name = ""
            for component in components:
                comp = name_map.get(component, component[:n_letters])
                name += (
                    f'{comp}{target.concentration[component].to("mg/ml").magnitude:.2f}'
                )
            target.name = name + "-mgml"

    def balance(self, tol=0.05):
        stocks = self._stock_objs()
        if any([stock.location is None for stock in stocks]):
            raise ValueError(
                "Some stocks don't have a location specified. This should be specified when the stocks are instantiated"
            )
        self._set_bounds(stocks)
        components = list(self.components)
        target_masses = np.zeros(len(components))
        balanced_masses = np.zeros(len(components))
        self.balanced = []
        for target in self.targets:
            _extract_masses(target, components, array=target_masses)
            mass_transfers = _balance(
                self.mass_fraction_matrix(stocks), target_masses, self.bounds, stocks
            )
            balanced_targets = []
            for transfers in mass_transfers:
                balanced_target = _make_balanced_target(transfers, target)
                _extract_masses(balanced_target, components, array=balanced_masses)
                difference = (balanced_masses - target_masses) / target_masses
                if all(difference < tol):
                    balanced_targets.append(
                        {
                            "target": balanced_target,
                            "difference": difference,
                            "transfers": transfers,
                        }
                    )
            if not balanced_targets:
                warnings.warn(f"No suitable mass balance found for {target.name}")
                self.balanced.append(
                    {
                        "target": target,
                        "balanced_target": None,
                        "transfers": None,
                    }
                )
            else:
                balanced_target = min(
                    balanced_targets, key=lambda x: sum(x["difference"])
                )
                self.balanced.append(
                    {
                        "target": target,
                        "balanced_target": balanced_target["target"],
                        "transfers": balanced_target["transfers"],
                    }
                )

    def _set_bounds(self):
        raise NotImplementedError


# --- MassBalanceContext ---
class MassBalance(MassBalanceBase, Context):
    def __init__(self, name="MassBalance", minimum_volume="20 ul"):
        Context.__init__(self, name=name)
        MassBalanceBase.__init__(self)
        self.context_type = "MassBalance"
        self.config = {"stocks": [], "targets": [], "minimum_volume": minimum_volume}
        self.targets = []
        self.minimum_volume = enforce_units(minimum_volume, "volume")

    def __call__(self, reset=False, reset_stocks=False, reset_targets=False):
        if reset or reset_stocks:
            self.config["stocks"] = []
        if reset or reset_targets:
            self.targets.clear()
            self.config["targets"] = []
        return self

    @property
    def stock_components(self) -> Set[str]:
        stocks = self._stock_objs()
        return {component for stock in stocks for component in stock.components}

    @property
    def target_components(self) -> Set[str]:
        return {component for target in self.targets for component in target.components}

    def _set_bounds(self, stocks: Optional[List[Solution]] = None):
        if stocks is None:
            stocks = self._stock_objs()
        self.bounds = Bounds(
            lb=[
                stock.measure_out(self.minimum_volume).mass.to("g").magnitude
                for stock in stocks
            ],
            ub=[np.inf] * len(stocks),
            keep_feasible=False,
        )


# --- MassBalanceDriver ---
class MassBalanceDriver(MassBalanceBase, Driver):
    defaults = {"minimum_volume": "20 ul", "stocks": [], "targets": [], "tol": 1e-3}

    def __init__(self, overrides=None):
        MassBalance.__init__(self)
        Driver.__init__(
            self,
            name="MassBalance",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )
        self.minimum_transfer_volume = None
        self.targets = []

    @property
    def stock_components(self) -> Set[str]:
        stocks = self._stock_objs()
        if not stocks:
            raise ValueError(
                "No stocks have been added; add_stock must be called before accessing components"
            )
        return {component for stock in stocks for component in stock.components}

    @property
    def target_components(self) -> Set[str]:
        if not self.targets:
            raise ValueError(
                "No targets have been added; add_target must be called before accessing components"
            )
        return {component for target in self.targets for component in target.components}

    def process_stocks(self):
        """Deprecated: stocks are now derived directly from ``config['stocks']``."""
        return self._stock_objs()

    def process_targets(self):
        self.targets = []
        for target_config in self.config["targets"]:
            target = Solution(**target_config)
            self.targets.append(target)

    def add_stock(self, solution: Dict, reset: bool = False):
        if reset:
            self.reset_stocks()
        self.config["stocks"] = self.config["stocks"] + [solution]

    def add_target(self, target: Dict, reset: bool = False):
        if reset:
            self.reset_targets()
        self.config["targets"] = self.config["targets"] + [target]

    def reset_stocks(self):
        self.config["stocks"] = []

    def reset_targets(self):
        self.config["targets"] = []

    def _set_bounds(self, stocks: Optional[List[Solution]] = None):
        self.minimum_transfer_volume = enforce_units(
            self.config["minimum_volume"], "volume"
        )
        if stocks is None:
            stocks = self._stock_objs()
        self.bounds = Bounds(
            lb=[
                stock.measure_out(self.minimum_transfer_volume).mass.to("g").magnitude
                for stock in stocks
            ],
            ub=[np.inf] * len(stocks),
            keep_feasible=False,
        )

    def balance(self):
        self.process_targets()
        super().balance(tol=self.config["tol"])
