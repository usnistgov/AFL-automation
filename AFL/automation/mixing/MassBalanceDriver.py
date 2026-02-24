import pathlib
import warnings
from typing import List, Dict

import numpy as np
from scipy.optimize import Bounds

from AFL.automation.mixing.MassBalanceBase import MassBalanceBase
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.shared.units import enforce_units


def _is_finite(v):
    """Return True if *v* is a finite float (not NaN, inf, or -inf)."""
    import math
    return isinstance(v, (int, float)) and math.isfinite(v)


def _solution_to_display_dict(solution):
    """Build a JSON-serializable dict from a Solution with all available
    composition methods.

    Every property access and per-component computation is individually
    wrapped so one bad component never takes out the entire dict, and
    non-finite floats (NaN / inf) are filtered to ``None``.
    """

    def qty_to_dict(q, target_unit=None):
        if q is None:
            return None
        try:
            if target_unit:
                q = q.to(target_unit)
            mag = float(q.magnitude)
            if not _is_finite(mag):
                return None
            return {'value': round(mag, 6), 'units': str(q.units)}
        except Exception:
            return None

    out = {
        'name': solution.name,
        'location': solution.location,
        'components': list(solution.components.keys()),
    }

    # ---- Total mass / volume ----
    try:
        out['total_mass'] = qty_to_dict(solution.mass, 'mg')
    except Exception:
        pass
    try:
        out['total_volume'] = qty_to_dict(solution.volume, 'ul')
    except Exception:
        pass

    # Cache totals for per-component calculations below
    total_mass_mg = None
    try:
        m = solution.mass
        if m is not None:
            total_mass_mg = float(m.to('mg').magnitude)
            if not _is_finite(total_mass_mg) or total_mass_mg < 1e-12:
                total_mass_mg = None
    except Exception:
        pass

    total_vol_ul = None
    try:
        v = solution.volume
        if v is not None:
            total_vol_ul = float(v.to('ul').magnitude)
            if not _is_finite(total_vol_ul) or total_vol_ul < 1e-12:
                total_vol_ul = None
    except Exception:
        pass

    # ---- Per-component properties (each wrapped individually) ----
    masses = {}
    volumes = {}
    concentrations = {}
    mass_fractions = {}

    for name, comp in solution:
        # Mass
        try:
            if comp.mass is not None:
                masses[name] = qty_to_dict(comp.mass, 'mg')
        except Exception:
            pass

        # Volume
        try:
            vol = getattr(comp, 'volume', None)
            if vol is not None and _is_finite(float(vol.magnitude)) and float(vol.magnitude) > 1e-12:
                volumes[name] = qty_to_dict(vol, 'ul')
        except Exception:
            pass

        # Concentration (component mass / solution volume)
        try:
            if comp.mass is not None and total_vol_ul is not None:
                conc = comp.mass.to('mg') / solution.volume.to('ml')
                concentrations[name] = qty_to_dict(conc, 'mg/ml')
        except Exception:
            pass

        # Mass fraction (component mass / solution mass)
        try:
            if comp.mass is not None and total_mass_mg is not None:
                frac = float((comp.mass / solution.mass).to('').magnitude)
                if _is_finite(frac):
                    mass_fractions[name] = round(frac, 6)
        except Exception:
            pass

    out['masses'] = masses
    if volumes:
        out['volumes'] = volumes
    if concentrations:
        out['concentrations'] = concentrations
    if mass_fractions:
        out['mass_fractions'] = mass_fractions

    # ---- Bulk properties (OK to fail entirely) ----

    # Volume fractions (solvents only)
    try:
        vf = solution.volume_fraction
        if vf:
            vf_out = {}
            for k, v in vf.items():
                mag = float(v.magnitude)
                if _is_finite(mag):
                    vf_out[k] = round(mag, 6)
            if vf_out:
                out['volume_fractions'] = vf_out
    except Exception:
        pass

    # Molarities (components with formulas only)
    try:
        mol = solution.molarity
        if mol:
            mol_out = {}
            for k, v in mol.items():
                d = qty_to_dict(v, 'mol/L')
                if d is not None:
                    mol_out[k] = d
            if mol_out:
                out['molarities'] = mol_out
    except Exception:
        pass

    # Molalities
    try:
        molal = solution.molality
        if molal:
            molal_out = {}
            for k, v in molal.items():
                d = qty_to_dict(v, 'mol/kg')
                if d is not None:
                    molal_out[k] = d
            if molal_out:
                out['molalities'] = molal_out
    except Exception:
        pass

    return out


class MassBalanceDriver(MassBalanceBase, Driver):
    defaults = {'minimum_volume': '20 ul', 'stocks': [], 'targets': [], 'tol': 1e-3, 'sweep_config': {}}


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
        self.useful_links['MixDoctor'] = 'mixdoctor'
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

    def upload_stocks(self, stocks=None, reset=True):
        if stocks is None:
            stocks = []
        prev_stocks = list(self.config['stocks'])
        prev_locs = dict(self.config['stock_locations']) if 'stock_locations' in self.config else {}
        try:
            if reset:
                self.reset_stocks()
            for stock in stocks:
                self.config['stocks'] = self.config['stocks'] + [stock]
                if 'stock_locations' in self.config and stock.get('location') is not None:
                    self.config['stock_locations'][stock['name']] = stock['location']
            self.process_stocks()
            return {'success': True, 'count': len(stocks)}
        except Exception as e:
            self.config['stocks'] = prev_stocks
            if 'stock_locations' in self.config:
                self.config['stock_locations'].clear()
                self.config['stock_locations'].update(prev_locs)
            try:
                self.process_stocks()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    @Driver.unqueued()
    def compute_stock_properties(self, stock=None, **kwargs):
        if not stock:
            return {}
        try:
            if isinstance(stock, str):
                import json
                stock = json.loads(stock)
            solution = Solution(**stock)
            return _solution_to_display_dict(solution)
        except Exception as e:
            return {'error': str(e)}

    def save_sweep_config(self, sweep_config=None):
        if sweep_config is None:
            sweep_config = {}
        self.config['sweep_config'] = sweep_config
        return {'success': True}

    @Driver.unqueued()
    def load_sweep_config(self):
        return self.config['sweep_config'] if 'sweep_config' in self.config else {}

    def upload_targets(self, targets=None, reset=True):
        if targets is None:
            targets = []
        errors = []
        for i, target in enumerate(targets):
            try:
                Solution(**target)
            except Exception as e:
                errors.append({'index': i, 'name': target.get('name', ''), 'error': str(e)})
        if errors:
            return {'success': False, 'errors': errors}
        if reset:
            self.reset_targets()
        self.config['targets'] = self.config['targets'] + targets
        return {'success': True, 'count': len(targets)}

    @Driver.unqueued()
    def list_stocks(self):
        self.process_stocks()
        return [_solution_to_display_dict(stock) for stock in self.stocks]

    @Driver.unqueued()
    def list_targets(self):
        self.process_targets()
        return [_solution_to_display_dict(target) for target in self.targets]

    @Driver.unqueued(render_hint='html')
    def mixdoctor(self, **kwargs):
        from jinja2 import Template
        base = pathlib.Path(__file__).parent.parent / "driver_templates" / "mixdoctor"
        html = Template((base / "mixdoctor.html").read_text())
        css = (base / "css" / "style.css").read_text()
        js = (base / "js" / "main.js").read_text()
        return html.render(inline_css=css, inline_js=js)

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
