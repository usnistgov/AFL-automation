from typing import Set

import numpy as np
from scipy.optimize import Bounds

from AFL.automation.mixing.MassBalanceBase import MassBalanceBase
from AFL.automation.mixing.Context import Context
from AFL.automation.shared.units import enforce_units


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
