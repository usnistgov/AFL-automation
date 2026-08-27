import copy
import warnings
from functools import wraps
from typing import Dict, Optional

from AFL.automation.mixcalc.MassBalance import MassBalance
from AFL.automation.mixcalc.MassBalanceDriver import MassBalanceDriver
from AFL.automation.prepare.PipetteAction import PipetteAction
from AFL.automation.mixcalc.Solution import Solution
from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared.utilities import listify


def capture_task_video(output_filename):
    """Optionally record one driver task when its runtime flag is enabled."""
    def decorator(func):
        @wraps(func)
        def wrapped(self, *args, **kwargs):
            if not kwargs.get("capture_task_video", False):
                return func(self, *args, **kwargs)
            self._start_task_video(func.__name__, output_filename=output_filename)
            try:
                return func(self, *args, **kwargs)
            finally:
                self._finish_task_video()
        return wrapped
    return decorator


class PrepareDriver(MassBalanceDriver):
    """Base class for prepare drivers.

    Subclasses provide transport/backend-specific execution while this class
    handles shared target conditioning and mass-balance feasibility/solve flow.
    """

    defaults = {
        "stocks": [],
        "fixed_compositions": {},
        "composition_format": "masses",
        "enable_multistep_dilution": False,
        "multistep_max_steps": 2,
        "multistep_diluent_policy": "primary_solvent",
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

    def _reset_prepare_state(self) -> None:
        """Clear transient preparation bookkeeping.

        This resets runtime and persisted state derived from stock processing
        and sample execution without touching backend-specific robot/session
        state.
        """
        self.stocks = []
        self.targets = []
        if "deck" in self.config:
            self.config["deck"] = {}
        if "occupied_sample_locations" in self.config:
            self.config["occupied_sample_locations"] = []
        if "stock_tip_locations" in self.config:
            self.config["stock_tip_locations"] = {}
        if "stock_tip_reservations" in self.config:
            self.config["stock_tip_reservations"] = {}
        if "reserved_stock_tips" in self.config:
            self.config["reserved_stock_tips"] = []

    def _condition_preparation_target(self, balanced_target: Solution) -> Solution:
        """Backend hook to adjust a planned preparation target before validation."""
        return balanced_target

    def _balance_target(self, target: dict, enable_multistep_dilution: bool) -> dict | None:
        """Plan one target through the common MassBalance result contract."""
        self._validate_stock_volume_fraction_sources(target)
        mb = MassBalance(minimum_volume=self.config.get("minimum_volume", "100 ul"))
        mb.stocks.extend(self.stocks)
        target_solution = Solution(**self.apply_fixed_comps(target.copy()))
        mb.targets.append(target_solution)
        mb.balance(
            tol=self.config.get("tol", 1e-3),
            enable_multistep_dilution=bool(enable_multistep_dilution),
            multistep_max_steps=int(self.config.get("multistep_max_steps", 2)),
            multistep_diluent_policy=str(self.config.get("multistep_diluent_policy", "primary_solvent")),
        )
        if not mb.balanced or mb.balanced[0].get("balanced_target") is None:
            return None
        entry = mb.balanced[0]
        entry["balanced_target"] = self._condition_preparation_target(
            entry["balanced_target"]
        )
        self._validate_pipette_action_plan(entry["balanced_target"].protocol)
        return entry

    def _validate_stock_volume_fraction_sources(self, target: dict) -> None:
        """Ensure a direct stock recipe only names currently available stocks."""
        requested_stocks = target.get("stock_volume_fractions", {})
        if not requested_stocks:
            return

        available_stocks = {
            getattr(stock, "stock_group", stock.name)
            for stock in self.stocks
        }
        missing_stocks = sorted(set(requested_stocks) - available_stocks)
        if not missing_stocks:
            return

        configured_stocks = sorted(
            stock.get("name", "<unnamed>")
            for stock in self.config.get("stocks", [])
            if isinstance(stock, dict)
        )
        configured_summary = ", ".join(configured_stocks) if configured_stocks else "none"
        raise ValueError(
            "Direct stock recipe requires available configured stock(s): "
            f"{', '.join(missing_stocks)}. Configure or restore these stocks before "
            f"retrying. Currently configured stocks: {configured_summary}."
        )

    def is_feasible(
        self,
        targets: dict | list[dict],
        enable_multistep_dilution: bool | None = None,
    ) -> list[dict | None]:
        targets_to_check = listify(targets)
        self.process_stocks()
        self.last_feasibility_errors = []
        if enable_multistep_dilution is None:
            enable_multistep_dilution = bool(self.config.get("enable_multistep_dilution", False))

        results: list[dict | None] = []
        for target in targets_to_check:
            try:
                entry = self._balance_target(target, bool(enable_multistep_dilution))
                results.append(entry["balanced_target"].to_dict() if entry else None)
            except Exception as e:
                message = (
                    f"Feasibility check for target {target.get('name', 'Unnamed')!r} "
                    f"failed: {e}"
                )
                self.last_feasibility_errors.append(message)
                self.log_warning(message)
                warnings.warn(message, stacklevel=2)
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


    def _validate_pipette_action_plan(self, protocol: list[PipetteAction]) -> None:
        """Validate a planned transfer protocol.

        Subclasses may override this to enforce backend-specific pipette
        constraints. The default implementation accepts all plans.
        """
        return None

    def resolve_destination(self, dest: Optional[str]) -> str:
        """Return destination identifier for this backend."""
        raise NotImplementedError("PrepareDriver subclasses must implement resolve_destination().")

    def execute_preparation(self, target: dict, balanced_target: Solution, destination: str) -> bool:
        """Execute backend-specific prepare actions.

        Returns False for handled, non-fatal failures where caller should return
        (None, None). Raise for hard failures.
        """
        raise NotImplementedError("PrepareDriver subclasses must implement execute_preparation().")

    def execute_preparation_plan(
        self,
        target: dict,
        balanced_target: Solution,
        destination: str,
        procedure_plan: dict,
        intermediate_destinations: list[str],
    ) -> bool:
        if procedure_plan.get("required_intermediate_targets", 0) > 0:
            raise NotImplementedError(
                "This prepare backend does not implement multi-step execution."
            )
        return self.execute_preparation(target, balanced_target, destination)

    def on_prepare_exception(self, destination: str, dest_was_none: bool) -> None:
        """Subclass hook to rollback destination bookkeeping on exceptions."""

    def build_prepare_result(self, feasible_result: dict, balanced_target: Solution) -> dict:
        """Build return payload for prepare()."""
        return feasible_result

    def _ensure_prepare_metadata(self) -> dict | None:
        if self.data is None:
            return None

        prepare_meta = self.data.get("prepare")
        if not isinstance(prepare_meta, dict):
            prepare_meta = {}
            self.data["prepare"] = prepare_meta
        prepare_meta.setdefault("executed_transfers", [])
        return prepare_meta

    def _update_prepare_metadata(self, **updates) -> dict | None:
        prepare_meta = self._ensure_prepare_metadata()
        if prepare_meta is None:
            return None
        for key, value in updates.items():
            prepare_meta[key] = value
        return prepare_meta

    def _append_prepare_transfer(self, transfer_entry: dict) -> None:
        prepare_meta = self._ensure_prepare_metadata()
        if prepare_meta is None:
            return
        executed = prepare_meta.setdefault("executed_transfers", [])
        executed.append(copy.deepcopy(transfer_entry))

    def _serialize_planned_mass_transfers(self, planned_mass_transfers: dict | None) -> dict | None:
        if planned_mass_transfers is None:
            return None

        serialized = {}
        for stock, mass in planned_mass_transfers.items():
            stock_key = stock.name if hasattr(stock, "name") else str(stock)
            serialized[stock_key] = mass
        return serialized

    def _augment_prepare_result(
        self,
        result: dict,
        destination: str,
        intermediate_destinations: list[str],
        planned_mass_transfers: dict | None,
        procedure_plan: dict,
    ) -> dict:
        augmented = copy.deepcopy(result)
        augmented["destination"] = destination
        augmented["intermediate_destinations"] = list(intermediate_destinations)
        augmented["procedure_plan"] = copy.deepcopy(procedure_plan)
        augmented["planned_mass_transfers"] = self._serialize_planned_mass_transfers(
            planned_mass_transfers
        )
        prepare_meta = self._ensure_prepare_metadata()
        if prepare_meta is not None:
            augmented["executed_transfers"] = copy.deepcopy(
                prepare_meta.get("executed_transfers", [])
            )
        return augmented

    def _destination_queue_key(self) -> str | None:
        if "prep_targets" in self.config:
            return "prep_targets"
        if "mixing_locations" in self.config:
            return "mixing_locations"
        return None

    def _reserve_destinations(
        self,
        dest: str | None,
        required_intermediate_targets: int,
    ) -> tuple[str, list[str], list[str], str | None]:
        if required_intermediate_targets <= 0:
            destination = self.resolve_destination(dest)
            return destination, [], [], None

        queue_key = self._destination_queue_key()
        if queue_key is None:
            raise ValueError(
                "Multi-step prepare requires a configured destination queue (prep_targets or mixing_locations)."
            )
        queue = list(self.config.get(queue_key, []))
        needed = required_intermediate_targets + (0 if dest is not None else 1)
        if len(queue) < needed:
            raise ValueError(
                f"Not enough {queue_key} entries for multi-step preparation. "
                f"Need {needed}, found {len(queue)}."
            )
        consumed = queue[:needed]
        self.config[queue_key] = queue[needed:]
        intermediate_destinations = consumed[:required_intermediate_targets]
        destination = dest if dest is not None else consumed[required_intermediate_targets]
        return destination, intermediate_destinations, consumed, queue_key

    def _restore_reserved_destinations(self, queue_key: str | None, consumed: list[str]) -> None:
        if not queue_key or not consumed:
            return
        queue = list(self.config.get(queue_key, []))
        self.config[queue_key] = consumed + queue

    @capture_task_video("prepare.mp4")
    def prepare(
        self,
        target: dict,
        dest: str | None = None,
        enable_multistep_dilution: bool | None = None,
        capture_task_video: bool = False,
    ) -> tuple[dict, str] | tuple[None, None]:
        requested_target = copy.deepcopy(target)
        target = self.apply_fixed_comps(target)
        if enable_multistep_dilution is None:
            enable_multistep_dilution = bool(self.config.get("enable_multistep_dilution", False))
        self._update_prepare_metadata(
            requested_target=requested_target,
            applied_target=copy.deepcopy(target),
            requested_destination=dest,
            destination=None,
            intermediate_destinations=[],
            enable_multistep_dilution=bool(enable_multistep_dilution),
            feasible_result=None,
            balanced_target=None,
            planned_mass_transfers=None,
            procedure_plan=None,
            execution_success=False,
        )

        feasibility_results = self.is_feasible(
            target,
            enable_multistep_dilution=bool(enable_multistep_dilution),
        )
        if not feasibility_results or feasibility_results[0] is None:
            feasibility_error = (
                self.last_feasibility_errors[0]
                if self.last_feasibility_errors
                else "No mass-balance solution was found."
            )
            self._update_prepare_metadata(
                feasible_result=None,
                balanced_target=None,
                planned_mass_transfers=None,
                procedure_plan=None,
                feasibility_error=feasibility_error,
                execution_success=False,
            )
            message = (
                f"Target composition {target.get('name', 'Unnamed target')} is not feasible: "
                f"{feasibility_error}"
            )
            self.log_warning(message)
            raise ValueError(message)

        feasible_result = feasibility_results[0]

        self.before_balance(target)

        self.reset_targets()
        self.add_target(target)
        self.balance(enable_multistep_dilution=bool(enable_multistep_dilution))

        if not self.balanced or not self.balanced[0].get("balanced_target"):
            warnings.warn(
                f"No suitable mass balance found for target: {target.get('name', 'Unnamed target')}",
                stacklevel=2,
            )
            procedure_plan = self.balanced[0].get("procedure_plan") or {}
            self._update_prepare_metadata(
                feasible_result=copy.deepcopy(feasible_result),
                balanced_target=None,
                planned_mass_transfers=self._serialize_planned_mass_transfers(
                    self.balanced[0].get("transfers")
                ),
                procedure_plan=copy.deepcopy(procedure_plan),
                execution_success=False,
            )
            return None, None

        balanced_target = self.balanced[0]["balanced_target"]
        balanced_target = self._condition_preparation_target(balanced_target)
        self.balanced[0]["balanced_target"] = balanced_target
        self._validate_pipette_action_plan(balanced_target.protocol)
        procedure_plan = self.balanced[0].get("procedure_plan") or {}
        planned_mass_transfers = self.balanced[0].get("transfers")
        required_intermediate_targets = int(procedure_plan.get("required_intermediate_targets", 0))
        destination, intermediate_destinations, consumed, queue_key = self._reserve_destinations(
            dest=dest,
            required_intermediate_targets=required_intermediate_targets,
        )
        self._update_prepare_metadata(
            feasible_result=copy.deepcopy(feasible_result),
            balanced_target=balanced_target.to_dict(),
            planned_mass_transfers=self._serialize_planned_mass_transfers(planned_mass_transfers),
            procedure_plan=copy.deepcopy(procedure_plan),
            destination=destination,
            intermediate_destinations=list(intermediate_destinations),
        )

        try:
            if required_intermediate_targets > 0:
                success = self.execute_preparation_plan(
                    target=target,
                    balanced_target=balanced_target,
                    destination=destination,
                    procedure_plan=procedure_plan,
                    intermediate_destinations=intermediate_destinations,
                )
            else:
                success = self.execute_preparation(target, balanced_target, destination)
            if success is False:
                self._update_prepare_metadata(execution_success=False)
                return None, None
        except Exception:
            self._update_prepare_metadata(execution_success=False)
            if required_intermediate_targets > 0:
                self._restore_reserved_destinations(queue_key=queue_key, consumed=consumed)
            else:
                self.on_prepare_exception(destination=destination, dest_was_none=(dest is None))
            raise

        self._update_prepare_metadata(execution_success=True)
        result = self.build_prepare_result(feasible_result, balanced_target)
        return self._augment_prepare_result(
            result=result,
            destination=destination,
            intermediate_destinations=intermediate_destinations,
            planned_mass_transfers=planned_mass_transfers,
            procedure_plan=procedure_plan,
        ), destination
