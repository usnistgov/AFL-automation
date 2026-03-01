import warnings
from typing import Dict, Optional

from AFL.automation.mixcalc.MassBalance import MassBalance
from AFL.automation.mixcalc.MassBalanceDriver import MassBalanceDriver
from AFL.automation.mixcalc.Solution import Solution
from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared.utilities import listify


class PrepareDriver(MassBalanceDriver):
    """Base class for prepare drivers.

    Subclasses provide transport/backend-specific execution while this class
    handles shared target conditioning and mass-balance feasibility/solve flow.
    """

    defaults = {
        "stocks": [],
        "fixed_compositions": {},
    }

    def __init__(self, driver_name: str, overrides=None):
        MassBalanceDriver.__init__(self, overrides=overrides)

        self.name = driver_name
        self.filepath = self.path / (self.name + ".config.json")
        self.config = PersistentConfig(
            path=self.filepath,
            defaults=self.gather_defaults(),
            overrides=overrides,
            max_history=100,
            max_history_size_mb=50,
            write_debounce_seconds=0.5,
            compact_json=True,
        )

        self.stocks = []
        self.targets = []
        self.process_stocks()

    def status(self):
        status = []
        status.append(f"AFL Server Stocks: {self.config['stocks']}")
        status.extend(self._status_lines())
        return status

    def _status_lines(self) -> list[str]:
        """Subclass hook for additional status lines."""
        return []

    def is_feasible(self, targets: dict | list[dict]) -> list[dict | None]:
        targets_to_check = listify(targets)
        self.process_stocks()
        minimum_volume = self.config.get("minimum_volume", "100 ul")

        results: list[dict | None] = []
        for target in targets_to_check:
            try:
                mb = MassBalance(minimum_volume=minimum_volume)
                for stock in self.stocks:
                    mb.stocks.append(stock)

                target_with_fixed = self.apply_fixed_comps(target.copy())
                target_solution = Solution(**target_with_fixed)
                mb.targets.append(target_solution)
                mb.balance(tol=self.config.get("tol", 1e-3))

                if (
                    mb.balanced
                    and len(mb.balanced) > 0
                    and mb.balanced[0].get("balanced_target") is not None
                ):
                    results.append(mb.balanced[0]["balanced_target"].to_dict())
                else:
                    results.append(None)
            except Exception as e:
                warnings.warn(
                    f"Exception during feasibility check for target "
                    f"{target.get('name', 'Unnamed')}: {str(e)}",
                    stacklevel=2,
                )
                results.append(None)
        return results

    def apply_fixed_comps(self, target: dict) -> dict:
        result = target.copy()
        fixed_comps = self.config.get("fixed_compositions", {})
        if not fixed_comps:
            return result

        for prop_type in ["masses", "volumes", "concentrations", "mass_fractions"]:
            if prop_type not in result:
                result[prop_type] = {}
            if prop_type in fixed_comps:
                for comp_name, comp_value in fixed_comps[prop_type].items():
                    if comp_name not in result[prop_type]:
                        result[prop_type][comp_name] = comp_value

        for prop in ["total_mass", "total_volume", "name", "location"]:
            if prop in fixed_comps and prop not in result:
                result[prop] = fixed_comps[prop]

        if "solutes" in fixed_comps:
            if "solutes" not in result:
                result["solutes"] = fixed_comps["solutes"].copy()
            else:
                for solute in fixed_comps["solutes"]:
                    if solute not in result["solutes"]:
                        result["solutes"].append(solute)

        return result

    def before_balance(self, target: dict) -> None:
        """Subclass hook to perform backend-specific checks before solving."""

    def resolve_destination(self, dest: Optional[str]) -> str:
        """Return destination identifier for this backend."""
        raise NotImplementedError("PrepareDriver subclasses must implement resolve_destination().")

    def execute_preparation(self, target: dict, balanced_target: Solution, destination: str) -> bool:
        """Execute backend-specific prepare actions.

        Returns False for handled, non-fatal failures where caller should return
        (None, None). Raise for hard failures.
        """
        raise NotImplementedError("PrepareDriver subclasses must implement execute_preparation().")

    def on_prepare_exception(self, destination: str, dest_was_none: bool) -> None:
        """Subclass hook to rollback destination bookkeeping on exceptions."""

    def build_prepare_result(self, feasible_result: dict, balanced_target: Solution) -> dict:
        """Build return payload for prepare()."""
        return feasible_result

    def prepare(self, target: dict, dest: str | None = None) -> tuple[dict, str] | tuple[None, None]:
        target = self.apply_fixed_comps(target)

        feasibility_results = self.is_feasible(target)
        if not feasibility_results or feasibility_results[0] is None:
            warnings.warn(
                f"Target composition {target.get('name', 'Unnamed target')} is not feasible "
                f"based on mass balance calculations",
                stacklevel=2,
            )
            return None, None

        feasible_result = feasibility_results[0]

        self.before_balance(target)

        self.reset_targets()
        self.add_target(target)
        self.balance()

        if not self.balanced or not self.balanced[0].get("balanced_target"):
            warnings.warn(
                f"No suitable mass balance found for target: {target.get('name', 'Unnamed target')}",
                stacklevel=2,
            )
            return None, None

        balanced_target = self.balanced[0]["balanced_target"]
        destination = self.resolve_destination(dest)

        try:
            success = self.execute_preparation(target, balanced_target, destination)
            if success is False:
                return None, None
        except Exception:
            self.on_prepare_exception(destination=destination, dest_was_none=(dest is None))
            raise

        return self.build_prepare_result(feasible_result, balanced_target), destination
