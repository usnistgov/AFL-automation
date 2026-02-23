import warnings
from typing import List, Dict

import numpy as np
from scipy.optimize import Bounds

from AFL.automation.mixing.MassBalanceBase import MassBalanceBase
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.shared.units import enforce_units


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
    def stock_components(self):
        if not self.stocks:
            raise ValueError('No stocks have been added; Must call process_stocks before accessing components')
        return {component for stock in self.stocks for component in stock.components}

    @property
    def target_components(self):
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


if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
