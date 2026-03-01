import contextlib
import io
import sys
import time
import warnings
from typing import List, Dict

import numpy as np
from scipy.optimize import Bounds

from AFL.automation.mixing.MassBalanceBase import MassBalanceBase
from AFL.automation.mixing.MassBalanceWebAppMixin import MassBalanceWebAppMixin
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

    # Solute list
    try:
        solute_names = [name for name, comp in solution if comp.is_solute]
        if solute_names:
            out['solutes'] = solute_names
    except Exception:
        pass

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


class MassBalanceDriver(MassBalanceBase, MassBalanceWebAppMixin, Driver):
    defaults = {
        'minimum_volume': '20 ul',
        'stocks': [],
        'targets': [],
        'tol': 1e-3,
        'sweep_config': {},
        'orchestrator_uri': '',
        'orchestrator_username': 'Orchestrator',
        'prepare_uri': '',
        'prepare_username': 'Prepare',
    }


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
        self._balance_progress = {
            'active': False,
            'completed': 0,
            'total': 0,
            'fraction': 0.0,
            'eta_s': None,
            'elapsed_s': 0.0,
            'current_target': None,
            'current_target_idx': None,
            'message': 'idle',
        }
        self._balance_started_ts = None
        try:
            self.mixdb = MixDB.get_db()
        except ValueError:
            self.mixdb = MixDB()
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
        self._process_stocks_with_diagnostics(False)

    def _process_stocks_with_diagnostics(self, capture_diagnostics):
        new_stocks = []
        diagnostics = []
        if capture_diagnostics:
            self.last_stock_load_diagnostics = diagnostics
        for idx, stock_config in enumerate(self.config['stocks']):
            if capture_diagnostics:
                stock, diag = self._build_solution_with_diagnostics(stock_config, idx)
                if diag:
                    diagnostics.append(diag)
            else:
                stock = Solution(**stock_config)
            new_stocks.append(stock)
            if 'stock_locations' in self.config and stock.location is not None:
                self.config['stock_locations'][stock.name] = stock.location
        self.stocks = new_stocks
        return diagnostics

    @staticmethod
    def _build_solution_with_diagnostics(stock_config, idx):
        class _TeeIO(io.StringIO):
            def __init__(self, *streams):
                super().__init__()
                self._streams = streams

            def write(self, s):
                for stream in self._streams:
                    stream.write(s)
                return super().write(s)

            def flush(self):
                for stream in self._streams:
                    stream.flush()
                return super().flush()

        stdout_buf = _TeeIO(sys.stdout)
        stderr_buf = _TeeIO(sys.stderr)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                solution = Solution(**stock_config)

        warnings_list = []
        for w in caught:
            warnings_list.append({
                'category': w.category.__name__,
                'message': str(w.message),
                'filename': w.filename,
                'lineno': w.lineno,
            })
            warnings.showwarning(w.message, w.category, w.filename, w.lineno)

        stdout_text = stdout_buf.getvalue().strip()
        stderr_text = stderr_buf.getvalue().strip()

        diag = {
            'index': idx,
            'name': stock_config.get('name'),
            'warnings': warnings_list,
        }
        if stdout_text:
            diag['stdout'] = stdout_text
        if stderr_text:
            diag['stderr'] = stderr_text

        if not warnings_list and not stdout_text and not stderr_text:
            return solution, None
        return solution, diag

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
            diagnostics = self._process_stocks_with_diagnostics(True)
            return {'success': True, 'count': len(stocks), 'diagnostics': diagnostics}
        except Exception as e:
            self.config['stocks'] = prev_stocks
            if 'stock_locations' in self.config:
                self.config['stock_locations'].clear()
                self.config['stock_locations'].update(prev_locs)
            try:
                self.process_stocks()
            except Exception:
                pass
            resp = {'success': False, 'error': str(e)}
            diagnostics = getattr(self, 'last_stock_load_diagnostics', None)
            if diagnostics:
                resp['diagnostics'] = diagnostics
            return resp

    @Driver.unqueued()
    def compute_stock_properties(self, stock=None, **kwargs):
        if not stock:
            return {}
        try:
            if isinstance(stock, str):
                import json
                stock = json.loads(stock)
            stock = self._normalize_stock_for_conversion(stock)
            solution = Solution(**stock)
            return _solution_to_display_dict(solution)
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def _normalize_stock_for_conversion(stock):
        stock = dict(stock)
        masses = stock.get('masses') or {}
        volumes = stock.get('volumes') or {}
        concentrations = stock.get('concentrations') or {}
        molarities = stock.get('molarities') or {}
        molalities = stock.get('molalities') or {}
        mass_fractions = stock.get('mass_fractions') or {}
        volume_fractions = stock.get('volume_fractions') or {}
        solutes = stock.get('solutes') or []

        total_mass = stock.get('total_mass')
        total_volume = stock.get('total_volume')

        # If concentrations or molarities are specified, we must have a volume.
        if (concentrations or molarities) and not volumes and total_volume:
            target = list(concentrations.keys()) or list(molarities.keys())
            if target:
                volumes = dict(volumes)
                volumes[target[0]] = total_volume
                stock['volumes'] = volumes

        # If mass fractions exist without any mass context, seed a total mass.
        if mass_fractions and not total_mass and not total_volume and not masses:
            stock['total_mass'] = '1 mg'

        # If volume fractions exist without any volume context, seed a total volume.
        if volume_fractions and not total_volume and not total_mass and not volumes:
            stock['total_volume'] = '1 ml'

        # If molalities exist without any mass context, seed a solvent mass.
        if molalities and not masses and not total_mass:
            solvent = None
            for comp in molalities.keys():
                if comp not in solutes:
                    solvent = comp
                    break
            if solvent is None and molalities:
                solvent = list(molalities.keys())[0]
            if solvent:
                masses = dict(masses)
                masses[solvent] = '1 g'
                stock['masses'] = masses

        return stock

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

    @Driver.unqueued()
    def list_balanced_targets(self):
        results = self._collect_balanced_targets()
        if results:
            return results
        # Fall back to last cached results on disk (queue worker writes these)
        try:
            import json
            with open(self.filepath, 'r') as f:
                history = json.load(f)
            if history:
                latest_key = sorted(history.keys())[-1]
                cached = history[latest_key].get('balanced_targets_cache', [])
                if isinstance(cached, list):
                    return cached
        except Exception:
            pass
        return []

    def _collect_balanced_targets(self):
        if not self.balanced:
            return []
        results = []
        for entry in self.balanced:
            balanced_target = entry.get('balanced_target')
            if balanced_target is None:
                continue
            out = _solution_to_display_dict(balanced_target)
            out['source_target_name'] = entry['target'].name if entry.get('target') else None
            out['balance_success'] = entry.get('success')
            results.append(out)
        return results

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
        total = len(self.targets)
        self._balance_started_ts = time.time()
        self._balance_progress = {
            'active': True,
            'completed': 0,
            'total': total,
            'fraction': 0.0,
            'eta_s': None,
            'elapsed_s': 0.0,
            'current_target': None,
            'current_target_idx': None,
            'message': 'starting',
        }

        def _progress_cb(stage=None, completed=0, total=0, target_idx=None, target_name=None, **kwargs):
            now = time.time()
            elapsed = max(0.0, now - self._balance_started_ts) if self._balance_started_ts is not None else 0.0
            frac = (float(completed) / float(total)) if total else 1.0
            eta = None
            if completed > 0 and total > completed:
                eta = max(0.0, elapsed * ((float(total - completed)) / float(completed)))
            msg = stage if stage else 'running'
            self._balance_progress = {
                'active': True,
                'completed': int(completed),
                'total': int(total),
                'fraction': float(frac),
                'eta_s': eta,
                'elapsed_s': float(elapsed),
                'current_target': target_name,
                'current_target_idx': int(target_idx) if target_idx is not None else None,
                'message': msg,
            }

        try:
            result = super().balance(
                tol=self.config['tol'],
                return_report=return_report,
                progress_callback=_progress_cb,
            )
            try:
                self.config['balanced_targets_cache'] = self._collect_balanced_targets()
            except Exception:
                pass
            return result
        finally:
            now = time.time()
            elapsed = max(0.0, now - self._balance_started_ts) if self._balance_started_ts is not None else 0.0
            completed = self._balance_progress.get('completed', 0)
            total = self._balance_progress.get('total', total)
            frac = (float(completed) / float(total)) if total else 1.0
            self._balance_progress = {
                'active': False,
                'completed': int(completed),
                'total': int(total),
                'fraction': float(frac),
                'eta_s': 0.0 if completed >= total and total > 0 else None,
                'elapsed_s': float(elapsed),
                'current_target': self._balance_progress.get('current_target'),
                'current_target_idx': self._balance_progress.get('current_target_idx'),
                'message': 'done',
            }
            self._balance_started_ts = None

    @Driver.unqueued()
    def get_balance_progress(self):
        return dict(self._balance_progress)

    @Driver.unqueued()
    def get_balance_settings(self):
        return {'tol': self.config['tol']}

    def get_sample_composition(self, composition_format='mass_fraction'):
        """Get the composition of the last balanced target in the requested format.

        Uses the Solution objects in ``self.balanced`` which have full access
        to the component database, avoiding the need for the caller to
        reconstruct Solution objects.

        Parameters
        ----------
        composition_format : str or dict
            If str, a single format applied to all components.
            If dict, maps component names to format strings; components not
            listed default to ``'mass_fraction'``.
            Valid formats: ``'mass_fraction'``, ``'volume_fraction'``,
            ``'concentration'``, ``'molarity'``.

        Returns
        -------
        dict
            Composition dictionary with component names as keys and numeric
            values in the requested format.
        """
        valid_formats = ['mass_fraction', 'volume_fraction', 'concentration', 'molarity']

        if not self.balanced:
            raise ValueError("No balanced targets available. Call balance() first.")

        last_entry = self.balanced[-1]
        balanced_target = last_entry.get('balanced_target')

        if balanced_target is None:
            raise ValueError("Last balance attempt failed — no balanced target available.")

        sample_composition = {}

        if isinstance(composition_format, str):
            if composition_format not in valid_formats:
                raise ValueError(
                    f"Invalid composition_format '{composition_format}'. "
                    f"Must be one of: {', '.join(valid_formats)}"
                )
            for component in balanced_target.components.keys():
                sample_composition[component] = self._get_component_value(
                    balanced_target, component, composition_format
                )
        elif isinstance(composition_format, dict):
            for component in balanced_target.components.keys():
                format_type = composition_format.get(component, 'mass_fraction')
                if format_type not in valid_formats:
                    raise ValueError(
                        f"Invalid format '{format_type}' for component '{component}'. "
                        f"Must be one of: {', '.join(valid_formats)}"
                    )
                sample_composition[component] = self._get_component_value(
                    balanced_target, component, format_type
                )
        else:
            raise ValueError(
                f"composition_format must be str or dict, got {type(composition_format).__name__}"
            )

        return sample_composition

    @staticmethod
    def _get_component_value(solution, component, format_type):
        """Extract a component value in the specified format from a Solution.

        Parameters
        ----------
        solution : Solution
            Solution object containing the component.
        component : str
            Component name.
        format_type : str
            One of: ``'mass_fraction'``, ``'volume_fraction'``,
            ``'concentration'``, ``'molarity'``.

        Returns
        -------
        float
            Component value in the requested format (dimensionless or in
            canonical units: mg/ml for concentration, mM for molarity).
        """
        if format_type == 'mass_fraction':
            return solution.mass_fraction[component].magnitude

        elif format_type == 'volume_fraction':
            if solution[component].volume is None:
                raise ValueError(
                    f"Component {component} has no volume, cannot calculate volume_fraction. "
                    f"Only solvents support volume_fraction."
                )
            return solution.volume_fraction[component].magnitude

        elif format_type == 'concentration':
            return solution.concentration[component].to('mg/ml').magnitude

        elif format_type == 'molarity':
            if not hasattr(solution[component], 'formula') or solution[component].formula is None:
                raise ValueError(
                    f"Component {component} has no formula, cannot calculate molarity"
                )
            return solution.molarity[component].to('mM').magnitude

        else:
            raise ValueError(
                f"Invalid format_type '{format_type}'. "
                f"Must be one of: 'mass_fraction', 'volume_fraction', 'concentration', 'molarity'"
            )

    # --- Component database management ---

    @Driver.unqueued()
    def list_components(self):
        return self.mixdb.list_components()

    @Driver.unqueued()
    def add_component(self, **component):
        component.pop('r', None)
        uid = self.mixdb.add_component(component)
        self.mixdb.write()
        return uid

    @Driver.unqueued()
    def update_component(self, **component):
        component.pop('r', None)
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
