import warnings

from AFL.automation.prepare.OT2HTTPDriver import OT2HTTPDriver
from AFL.automation.prepare.PrepareDriver import PrepareDriver


class OT2Prepare(OT2HTTPDriver, PrepareDriver):
    defaults = {
        "prep_targets": [],
        "prepare_volume": "900 ul",
        "catch_volume": "900 ul",
        "deck": {},
        "stocks": [],
        "stock_mix_order": [],
        "fixed_compositions": {},
        "stock_locations": {},  # Maps stock names to deck positions: {'stockH2O': '3A2'}
        "stock_transfer_params": {},  # Per-stock transfer parameters: {'stockH2O': {'mix_after': True}}
        "catch_protocol": {},  # PipetteAction-formatted dict for catch transfer parameters
    }

    def __init__(self, overrides=None):
        OT2HTTPDriver.__init__(self, overrides=overrides)
        PrepareDriver.__init__(self, driver_name="OT2Prepare", overrides=overrides)
        self.last_target_location = None
        self.useful_links["View Deck"] = "/visualize_deck"

    def status(self):
        return PrepareDriver.status(self) + OT2HTTPDriver.status(self)

    def _status_lines(self):
        status = []
        status.append(f"Stocks: {len(self.stocks)} configured")
        status.append(f"Stock locations: {self.config['stock_locations']}")
        status.append(f"{len(self.config['prep_targets'])} preparation targets available")
        return status

    def resolve_destination(self, dest):
        if dest is not None:
            return dest
        if not self.config.get("prep_targets"):
            raise ValueError("No preparation targets configured. Cannot select a destination target.")
        prep_targets = self.config["prep_targets"]
        destination = prep_targets.pop(0)
        self.config["prep_targets"] = prep_targets
        return destination

    def execute_preparation(self, target, balanced_target, destination):
        if not hasattr(balanced_target, "protocol") or not balanced_target.protocol:
            raise ValueError("No protocol generated for the target solution")

        protocol = self.reorder_protocol(balanced_target.protocol)
        for step in protocol:
            source = step.source
            volume_ul = step.volume
            stock_name = self.config.get("deck", {}).get(source)
            if stock_name is None:
                raise ValueError(f"No stock name found for deck location: {source}")

            transfer_params = self.get_transfer_params(stock_name)
            try:
                self.transfer(
                    source=source,
                    dest=destination,
                    volume=volume_ul,
                    **transfer_params,
                )
            except Exception as e:
                warnings.warn(f"Transfer failed from {source} to {destination}: {str(e)}", stacklevel=2)
                return False

        self.last_target_location = destination
        return True

    def _resolve_stage_source(self, source_location, intermediate_map):
        if isinstance(source_location, str) and source_location.startswith("@intermediate:"):
            key = source_location.split(":", 1)[1]
            if key not in intermediate_map:
                raise ValueError(f"Unknown intermediate source token: {source_location}")
            return intermediate_map[key]
        return source_location

    def _transfer_stage(self, source, dest, volume_ul):
        stock_name = self.config.get("deck", {}).get(source)
        transfer_params = self.get_transfer_params(stock_name) if stock_name is not None else self.get_transfer_params("default")
        self.transfer(source=source, dest=dest, volume=volume_ul, **transfer_params)

    def execute_preparation_plan(self, target, balanced_target, destination, procedure_plan, intermediate_destinations):
        intermediate_ids = procedure_plan.get("intermediate_ids", [])
        if len(intermediate_ids) != len(intermediate_destinations):
            raise ValueError(
                f"Intermediate destination mismatch. Need {len(intermediate_ids)}, got {len(intermediate_destinations)}."
            )
        intermediate_map = {
            intermediate_id: intermediate_destinations[i]
            for i, intermediate_id in enumerate(intermediate_ids)
        }

        stages = procedure_plan.get("stages", [])
        for stage in stages:
            stage_type = stage.get("stage_type")
            if stage_type == "dilution":
                dest_token = stage.get("destination_token")
                if not isinstance(dest_token, str) or not dest_token.startswith("@intermediate:"):
                    raise ValueError(f"Invalid dilution destination token: {dest_token}")
                intermediate_id = dest_token.split(":", 1)[1]
                if intermediate_id not in intermediate_map:
                    raise ValueError(f"No destination assigned for intermediate '{intermediate_id}'")
                stage_dest = intermediate_map[intermediate_id]

                source_loc = self._resolve_stage_source(stage.get("source_location"), intermediate_map)
                diluent_loc = self._resolve_stage_source(stage.get("diluent_location"), intermediate_map)
                source_mass_g = float(stage.get("total_source_mass_g", 0.0))
                diluent_mass_g = float(stage.get("total_diluent_mass_g", 0.0))
                if source_mass_g > 0:
                    source_stock = self.stocks_by_location(source_loc)
                    source_volume = source_stock.measure_out(f"{source_mass_g} g").volume.to("ul").magnitude
                    self._transfer_stage(source_loc, stage_dest, source_volume)
                if diluent_mass_g > 0:
                    diluent_stock = self.stocks_by_location(diluent_loc)
                    diluent_volume = diluent_stock.measure_out(f"{diluent_mass_g} g").volume.to("ul").magnitude
                    self._transfer_stage(diluent_loc, stage_dest, diluent_volume)
            elif stage_type == "final_mix":
                for transfer in stage.get("transfers", []):
                    source_loc = self._resolve_stage_source(transfer.get("source_location"), intermediate_map)
                    vol_ul = float(transfer.get("required_volume_ul", 0.0))
                    if vol_ul <= 0:
                        continue
                    self._transfer_stage(source_loc, destination, vol_ul)
            else:
                raise ValueError(f"Unknown stage type '{stage_type}' in procedure plan")

        self.last_target_location = destination
        return True

    def stocks_by_location(self, location):
        for stock in self.stocks:
            if stock.location == location:
                return stock
        raise ValueError(f"No stock configured at location '{location}'")

    def build_prepare_result(self, feasible_result, balanced_target):
        result_dict = balanced_target.to_dict()
        if hasattr(balanced_target, "volume") and balanced_target.volume is not None:
            result_dict["total_volume"] = f"{balanced_target.volume.to('ul').magnitude} ul"
        return result_dict

    def process_stocks(self):
        PrepareDriver.process_stocks(self)
        self._update_deck_config()

    def _update_deck_config(self):
        deck_config = {}
        stock_locations = self.config.get("stock_locations", {})
        for stock_name, deck_location in stock_locations.items():
            deck_config[deck_location] = stock_name
        self.config["deck"] = deck_config

    def get_transfer_params(self, stock_name):
        stock_params = self.config.get("stock_transfer_params", {}).get(stock_name, {})
        default_params = self.config.get("stock_transfer_params", {}).get("default", {})
        params = default_params.copy()
        params.update(stock_params)
        return params

    def reorder_protocol(self, protocol):
        stock_mix_order = self.config.get("stock_mix_order", [])
        if not stock_mix_order:
            return protocol

        steps_by_source = {}
        for step in protocol:
            if step.source not in steps_by_source:
                steps_by_source[step.source] = []
            steps_by_source[step.source].append(step)

        reordered = []
        for stock_name in stock_mix_order:
            if stock_name in steps_by_source:
                reordered.extend(steps_by_source[stock_name])
                del steps_by_source[stock_name]

        for steps in steps_by_source.values():
            reordered.extend(steps)
        return reordered

    def transfer_to_catch(self, source=None, dest=None, **kwargs):
        catch_params = self.config.get("catch_protocol", {}).copy()
        if source is None:
            if self.last_target_location is None:
                raise ValueError(
                    "No source specified and no last target location available. "
                    "Call prepare() first or specify source."
                )
            source = self.last_target_location
        kwargs["source"] = source

        if dest is not None:
            kwargs["dest"] = dest

        catch_params.update(kwargs)
        if "dest" not in catch_params:
            raise ValueError("Destination 'dest' must be specified in catch_protocol config or as an argument.")

        try:
            self.transfer(**catch_params)
        except Exception as e:
            dest_val = catch_params.get("dest", "unknown")
            warnings.warn(
                f"Transfer to catch failed from {source} to {dest_val} using {catch_params}: {str(e)}",
                stacklevel=2,
            )
            raise

    def reset(self):
        self.reset_targets()
        self.reset_stocks()


_DEFAULT_PORT = 5002
if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
