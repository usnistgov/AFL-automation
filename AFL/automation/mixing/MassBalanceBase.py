import itertools
import warnings
from typing import List, Optional, Dict, Set, Callable, Any, Iterator

import numpy as np
from scipy.optimize import lsq_linear, Bounds

from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.BalanceDiagnosis import BalanceDiagnosis, FailureCode, FailureDetail


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


def _diagnose(
    target,
    transfers: np.ndarray,
    differences: np.ndarray,
    components: List[str],
    stocks: List[Solution],
    bounds: Bounds,
    tol: float,
    mass_fraction_matrix: np.ndarray,
    target_masses: np.ndarray,
    success: bool,
    max_stock_fractions: Optional[np.ndarray] = None,
    missing_component_mask: Optional[np.ndarray] = None,
) -> BalanceDiagnosis:
    """Analyse a balance result and return a structured diagnosis.

    Checks are ordered from specific root causes to general symptoms so that
    the most actionable codes appear first in the details list.
    """
    component_errors = {comp: float(differences[i]) for i, comp in enumerate(components)}
    total_target_mass = float(np.sum(target_masses))
    n_stocks = len(stocks)

    if success:
        return BalanceDiagnosis(success=True, component_errors=component_errors)

    details = []
    if max_stock_fractions is None:
        max_stock_fractions = np.max(mass_fraction_matrix, axis=1)
    if missing_component_mask is None:
        missing_component_mask = max_stock_fractions == 0.0

    # --- Check 1: MISSING_STOCK_COMPONENT ---
    # A required component is absent from every stock — cannot be achieved regardless
    # of volumes or concentrations.
    for i, comp in enumerate(components):
        if target_masses[i] > 1e-12 and bool(missing_component_mask[i]):
            details.append(FailureDetail(
                code=FailureCode.MISSING_STOCK_COMPONENT,
                description=(
                    f"Component '{comp}' is required by the target but is not present in any "
                    f"stock. Add a stock containing '{comp}'."
                ),
                affected_components=[comp],
            ))

    # --- Check 2: STOCK_CONCENTRATION_TOO_LOW ---
    # The target mass fraction for a component exceeds the maximum mass fraction
    # achievable from any single stock.  Even using that stock at 100% of the
    # mixture cannot satisfy the target.
    if total_target_mass > 1e-12:
        target_fracs = target_masses / total_target_mass
        for i, comp in enumerate(components):
            if target_masses[i] < 1e-12:
                continue
            max_stock_frac = float(max_stock_fractions[i])
            target_frac = float(target_fracs[i])
            if target_frac > max_stock_frac + 1e-9:
                best_stock_idx = int(np.argmax(mass_fraction_matrix[i, :]))
                best_stock_name = stocks[best_stock_idx].name
                details.append(FailureDetail(
                    code=FailureCode.STOCK_CONCENTRATION_TOO_LOW,
                    description=(
                        f"Target mass fraction for '{comp}' ({target_frac:.4f}) exceeds the "
                        f"maximum achievable from any single stock ({max_stock_frac:.4f}). "
                        f"Prepare a more concentrated '{comp}' stock."
                    ),
                    affected_components=[comp],
                    affected_stocks=[best_stock_name],
                    data={
                        "target_mass_fraction": target_frac,
                        "max_achievable_mass_fraction": max_stock_frac,
                        "best_available_stock": best_stock_name,
                    },
                ))

    # --- Check 3: TARGET_OUTSIDE_REACHABLE_COMPOSITIONS ---
    # Only fires when checks 1 & 2 did not already explain the infeasibility.
    # Runs lsq_linear with only non-negativity bounds (no minimum-volume constraint)
    # to determine whether the composition is geometrically achievable at all.
    # A non-zero residual means the target lies outside the convex hull of stock
    # compositions (the "pareto front" / reachable composition space).
    if not any(
        d.code in (FailureCode.MISSING_STOCK_COMPONENT, FailureCode.STOCK_CONCENTRATION_TOO_LOW)
        for d in details
    ):
        hull_bounds = Bounds(lb=[0.0] * n_stocks, ub=[np.inf] * n_stocks)
        hull_result = lsq_linear(mass_fraction_matrix, target_masses, bounds=hull_bounds)
        residual_norm = float(np.linalg.norm(hull_result.fun))
        if total_target_mass > 1e-12 and (residual_norm / total_target_mass) > tol:
            details.append(FailureDetail(
                code=FailureCode.TARGET_OUTSIDE_REACHABLE_COMPOSITIONS,
                description=(
                    f"Target composition cannot be achieved by any non-negative combination of "
                    f"available stocks (relative residual {residual_norm / total_target_mass:.4f} "
                    f"> tolerance {tol}). Consider adding new stocks or reformulating existing ones."
                ),
                data={
                    "residual_norm": residual_norm,
                    "total_target_mass": total_target_mass,
                    "relative_residual": residual_norm / total_target_mass,
                },
            ))

    # --- Check 4: BELOW_MINIMUM_PIPETTE_VOLUME ---
    # Fires in two related situations:
    # (a) A stock was zeroed out (excluded) because the required transfer is below
    #     the minimum pipettable volume, removing its components from the balance.
    # (b) A stock is active but pinned at its lower bound and still cannot deliver
    #     enough of a required component (the ideal transfer would be smaller than
    #     the minimum, so it is forced up, but the constraint is still binding).
    failed_comps = {components[i] for i in range(len(components)) if abs(differences[i]) >= tol}
    for idx, stock in enumerate(stocks):
        mass_val = float(transfers[idx])
        lb_val = float(bounds.lb[idx])
        if mass_val == 0.0 and lb_val > 0.0:
            # Case (a): stock excluded entirely.
            affected = [
                comp for j, comp in enumerate(components)
                if mass_fraction_matrix[j, idx] > 0.0 and comp in failed_comps
            ]
            if affected:
                details.append(FailureDetail(
                    code=FailureCode.BELOW_MINIMUM_PIPETTE_VOLUME,
                    description=(
                        f"Stock '{stock.name}' was excluded because the required transfer is "
                        f"below the minimum pipette volume (lower bound {lb_val:.4g} g). "
                        f"Try reducing minimum_volume, increasing target total_mass, or "
                        f"reformulating stocks."
                    ),
                    affected_components=affected,
                    affected_stocks=[stock.name],
                    data={"stock": stock.name, "lower_bound_g": lb_val, "reason": "excluded"},
                ))
        elif lb_val > 0.0 and mass_val > 0.0 and abs(mass_val - lb_val) / lb_val < 0.01:
            # Case (b): stock is used but pinned at its lower bound.  Check
            # whether any component it provides is still under-delivered.
            under_delivered = [
                comp for j, comp in enumerate(components)
                if mass_fraction_matrix[j, idx] > 0.0
                and comp in failed_comps
                and differences[j] < -tol
            ]
            if under_delivered:
                details.append(FailureDetail(
                    code=FailureCode.BELOW_MINIMUM_PIPETTE_VOLUME,
                    description=(
                        f"Stock '{stock.name}' is constrained to its minimum pipette volume "
                        f"({lb_val:.4g} g) and cannot deliver sufficient "
                        f"'{', '.join(under_delivered)}'. "
                        f"Try reducing minimum_volume, increasing target total_mass, or "
                        f"using a more concentrated stock for {', '.join(under_delivered)}."
                    ),
                    affected_components=under_delivered,
                    affected_stocks=[stock.name],
                    data={
                        "stock": stock.name,
                        "lower_bound_g": lb_val,
                        "transfer_g": mass_val,
                        "reason": "at_lower_bound",
                    },
                ))

    # --- Check 5: UNWANTED_STOCK_COMPONENT ---
    # A component the target wants zero of is nonzero in the balanced result
    # because a stock needed for other components also contains it.
    for i, comp in enumerate(components):
        if target_masses[i] >= 1e-12:
            continue
        if abs(differences[i]) < tol:
            continue
        contaminating = [
            stock.name
            for idx, stock in enumerate(stocks)
            if float(transfers[idx]) > 0.0 and mass_fraction_matrix[i, idx] > 0.0
        ]
        if contaminating:
            details.append(FailureDetail(
                code=FailureCode.UNWANTED_STOCK_COMPONENT,
                description=(
                    f"Component '{comp}' is not wanted (target = 0) but is introduced by "
                    f"{contaminating} which are needed for other components. "
                    f"Use a purer stock for those other components."
                ),
                affected_components=[comp],
                affected_stocks=contaminating,
                data={"component": comp, "error": float(differences[i])},
            ))

    # --- Check 6: TOLERANCE_EXCEEDED (catch-all) ---
    # Lists every component whose relative error exceeds the tolerance.
    tol_exceeded = [components[i] for i in range(len(components)) if abs(differences[i]) >= tol]
    if tol_exceeded:
        tol_exceeded_idx = [i for i in range(len(components)) if abs(differences[i]) >= tol]
        details.append(FailureDetail(
            code=FailureCode.TOLERANCE_EXCEEDED,
            description=f"{len(tol_exceeded)} component(s) exceed {tol * 100:.1f}% tolerance.",
            affected_components=tol_exceeded,
            data={components[i]: float(differences[i]) for i in tol_exceeded_idx},
        ))

    return BalanceDiagnosis(success=False, details=details, component_errors=component_errors)


def _iter_balance_candidates(
    mass_fraction_matrix: np.ndarray,
    target_masses: np.ndarray,
    bounds: Bounds,
    stocks: List[Solution],
    near_bound_tol: float = 0.1,
) -> Iterator[np.ndarray]:
    result = lsq_linear(mass_fraction_matrix, target_masses, bounds=bounds)
    base_mass_transfer = np.array(result.x, dtype=float)
    yield base_mass_transfer

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

            adjusted_transfer = np.zeros(len(stocks), dtype=float)
            for reduced_idx, stock_idx in enumerate(keep_indices):
                adjusted_transfer[stock_idx] = float(reduced_result.x[reduced_idx])

            yield adjusted_transfer


def _balance(
    mass_fraction_matrix: np.ndarray,
    target_masses: np.ndarray,
    bounds: Bounds,
    stocks: List[Solution],
    near_bound_tol: float = 0.1,
) -> List[np.ndarray]:
    return list(_iter_balance_candidates(mass_fraction_matrix, target_masses, bounds, stocks, near_bound_tol))


def _compute_differences(
    target_masses: np.ndarray,
    balanced_masses: np.ndarray,
    total_target_mass: float,
) -> np.ndarray:
    t = target_masses
    b = balanced_masses
    differences = np.zeros_like(t, dtype=float)

    zero_t = t == 0
    zero_b = b == 0
    both_zero = zero_t & zero_b

    # Target is zero but balanced is not
    if total_target_mass > 0:
        differences[zero_t & ~zero_b] = b[zero_t & ~zero_b] / total_target_mass
    else:
        differences[zero_t & ~zero_b] = 1.0

    # Target is non-zero
    nonzero_t = ~zero_t
    differences[nonzero_t] = np.abs(b[nonzero_t] - t[nonzero_t]) / t[nonzero_t]

    # Both zero already set to 0
    differences[both_zero] = 0.0
    return differences


def _make_transfer_dict(stocks: List[Solution], transfers: np.ndarray) -> Dict[Solution, str]:
    return {stock: f'{float(mass)} g' for stock, mass in zip(stocks, transfers)}


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

            entry['diagnosis'] = (
                item['diagnosis'].to_dict() if item.get('diagnosis') is not None else None
            )

            report.append(entry)
        return report

    def failure_summary(self) -> str:
        """Return a human-readable summary of all failed balance entries.

        Returns an empty string if all balances succeeded or no balances have
        been run yet.
        """
        lines = []
        for item in self.balanced:
            diagnosis = item.get('diagnosis')
            if diagnosis is not None and not diagnosis.success:
                target_name = item['target'].name if item.get('target') else '<unknown>'
                lines.append(f"Target: {target_name}")
                lines.append(diagnosis.summary())
                lines.append("")
        return "\n".join(lines).rstrip()

    def balance(self, tol=0.05, return_report=False, progress_callback: Optional[Callable[..., Any]] = None):
        if any([stock.location is None for stock in self.stocks]):
            raise ValueError("Some stocks don't have a location specified. This should be specified when the stocks are instantiated")
        self._set_bounds()
        components = list(self.components)
        mfm = np.zeros((len(components), len(self.stocks)))
        _extract_mass_fractions(self.stocks, components, mfm)
        max_stock_fractions = np.max(mfm, axis=1) if len(self.stocks) > 0 else np.zeros(len(components))
        missing_component_mask = max_stock_fractions == 0.0

        target_mass_matrix = np.zeros((len(self.targets), len(components)))
        for idx, target in enumerate(self.targets):
            _extract_masses(target, components, array=target_mass_matrix[idx])

        if progress_callback is not None:
            progress_callback(
                stage='start',
                completed=0,
                total=len(self.targets),
                target_idx=None,
                target_name=None,
            )

        self.balanced = []
        for target_idx, target in enumerate(self.targets):
            if progress_callback is not None:
                progress_callback(
                    stage='target_start',
                    completed=target_idx,
                    total=len(self.targets),
                    target_idx=target_idx,
                    target_name=target.name,
                )
            target_masses = target_mass_matrix[target_idx]
            best_candidate = None
            best_score = None
            any_success = False

            total_target_mass = float(np.sum(target_masses))

            for transfers in _iter_balance_candidates(mfm, target_masses, self.bounds, self.stocks):
                balanced_masses = mfm @ transfers
                differences = _compute_differences(
                    target_masses=target_masses,
                    balanced_masses=balanced_masses,
                    total_target_mass=total_target_mass,
                )
                score = float(np.sum(np.abs(differences)))
                success = bool(np.all(np.abs(differences) < tol))

                if best_candidate is None or score < best_score:
                    best_candidate = {
                        'target': None,
                        'difference': differences,
                        'transfers': transfers,
                        'success': success,
                    }
                    best_score = score

                if success:
                    any_success = True
                if best_score == 0.0:
                    break

            if best_candidate is None:
                raise RuntimeError("Mass balance produced no candidates; this should not happen.")

            diagnosis = _diagnose(
                target=target,
                transfers=best_candidate['transfers'],
                differences=best_candidate['difference'],
                components=components,
                stocks=self.stocks,
                bounds=self.bounds,
                tol=tol,
                mass_fraction_matrix=mfm,
                target_masses=target_masses,
                success=best_candidate['success'],
                max_stock_fractions=max_stock_fractions,
                missing_component_mask=missing_component_mask,
            )

            if not any_success:
                warnings.warn(f'No suitable mass balance found for {target.name}\n')
                self.balanced.append({
                    'target': target,
                    'balanced_target': None,
                    'transfers': None,
                    'difference': None,
                    'success': False,
                    'diagnosis': diagnosis,
                })
            else:
                transfers_dict = _make_transfer_dict(self.stocks, best_candidate['transfers'])
                balanced_target = _make_balanced_target(transfers_dict, target)
                self.balanced.append({
                    'target': target,
                    'balanced_target': balanced_target,
                    'transfers': transfers_dict,
                    'difference': best_candidate['difference'],
                    'success': best_candidate['success'],
                    'diagnosis': diagnosis,
                })
            if progress_callback is not None:
                progress_callback(
                    stage='target_end',
                    completed=target_idx + 1,
                    total=len(self.targets),
                    target_idx=target_idx,
                    target_name=target.name,
                    success=bool(any_success),
                )

        if progress_callback is not None:
            progress_callback(
                stage='done',
                completed=len(self.targets),
                total=len(self.targets),
                target_idx=None,
                target_name=None,
            )
        if return_report:
            return self.balance_report()


    def _set_bounds(self):
        raise NotImplementedError
