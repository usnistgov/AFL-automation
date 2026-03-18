import copy
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

    def is_feasible(
        self,
        targets: dict | list[dict],
        enable_multistep_dilution: bool | None = None,
    ) -> list[dict | None]:
        targets_to_check = listify(targets)
        self.process_stocks()
        minimum_volume = self.config.get("minimum_volume", "100 ul")
        if enable_multistep_dilution is None:
            enable_multistep_dilution = bool(self.config.get("enable_multistep_dilution", False))

        results: list[dict | None] = []
        for target in targets_to_check:
            try:
                mb = MassBalance(minimum_volume=minimum_volume)
                for stock in self.stocks:
                    mb.stocks.append(stock)

                target_with_fixed = self.apply_fixed_comps(target.copy())
                target_solution = Solution(**target_with_fixed)
                mb.targets.append(target_solution)
                mb.balance(
                    tol=self.config.get("tol", 1e-3),
                    enable_multistep_dilution=bool(enable_multistep_dilution),
                    multistep_max_steps=int(self.config.get("multistep_max_steps", 2)),
                    multistep_diluent_policy=str(self.config.get("multistep_diluent_policy", "primary_solvent")),
                )

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

    def prepare(
        self,
        target: dict,
        dest: str | None = None,
        enable_multistep_dilution: bool | None = None,
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
            self._update_prepare_metadata(
                feasible_result=None,
                balanced_target=None,
                planned_mass_transfers=None,
                procedure_plan=None,
                execution_success=False,
            )
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
