import warnings
import time
from typing import List, Union, Dict, Any, Optional, Tuple
from AFL.automation.mixing.MassBalance import MassBalanceDriver, MassBalance
from AFL.automation.prepare.OT2HTTPDriver import OT2HTTPDriver
from AFL.automation.shared.utilities import listify
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.PipetteAction import PipetteAction
from AFL.automation.APIServer.Driver import Driver


class OT2Prepare(OT2HTTPDriver, MassBalanceDriver):
    defaults = {
        "mixing_locations": [],
        "prepare_volume": "100 ul",
        "catch_volume": "10 ul",
        "deck": {},
        "stocks": [],
        "stock_mix_order": [],
        "fixed_compositions": {},
        "stock_locations": {},  # Maps stock names to deck positions: {'stockH2O': '3A2'}
        "stock_transfer_params": {},  # Per-stock transfer parameters: {'stockH2O': {'mix_after': True}}
    }

    def __init__(self, overrides=None):
        # Initialize both parent classes
        OT2HTTPDriver.__init__(self, overrides=overrides)
        MassBalanceDriver.__init__(self, overrides=overrides)

        # Override the name set by both parents
        self.name = "OT2Prepare"

        # Initialize additional attributes
        self.stocks = []
        self.targets = []

        self.useful_links["View Deck"] = "/visualize_deck"
        self.useful_links["Configure Stocks"] = "/configure_stocks"

    def status(self):
        """
        Get the status of the OT2Prepare driver.
        """
        # Get status from OT2HTTPDriver
        ot2_status = OT2HTTPDriver.status(self)

        # Add our own status information
        status = []
        status.append(f"Stocks: {len(self.stocks)} configured")
        status.append(f'Stock locations: {self.config["stock_locations"]}')
        status.append(
            f'{len(self.config["mixing_locations"])} mixing locations available'
        )

        # Combine status information
        return status + ot2_status

    def is_feasible(self, targets: dict | list[dict]) -> list[dict | None]:
        """
        Check if the target composition(s) is/are feasible for preparation using mass balance.
        If feasible, returns the balanced target solution dictionary. Otherwise, returns None.

        This implementation creates a local MassBalance instance for each feasibility check
        to avoid modifying the driver's state.

        Parameters
        ----------
        targets : Union[dict, List[dict]]
            Either a single target dictionary or a list of target dictionaries.

        Returns
        -------
        List[Union[dict, None]]
            A list containing the balanced target dictionary for each feasible target,
            or None for infeasible targets.
        """

        targets_to_check = listify(targets)

        # Process stocks from the driver if not already processed
        if not self.stocks:
            self.process_stocks()

        # Get the minimum volume configuration
        minimum_volume = self.config.get("minimum_volume", "100 ul")

        results = []
        for target in targets_to_check:
            try:
                # Create a local MassBalance instance
                mb = MassBalance(minimum_volume=minimum_volume)

                # Configure the same stocks as in the driver
                for stock in self.stocks:
                    mb.stocks.append(stock)

                # Apply any fixed compositions from config
                target_with_fixed = self.apply_fixed_comps(target.copy())

                # Create a Solution from the target and add it to the MassBalance instance
                from AFL.automation.mixing.Solution import Solution

                target_solution = Solution(**target_with_fixed)
                mb.targets.append(target_solution)

                # Calculate mass balance
                mb.balance(tol=self.config.get("tol", 1e-3))

                # Check if balance was successful for this target
                if (
                    mb.balanced
                    and len(mb.balanced) > 0
                    and mb.balanced[0].get("balanced_target") is not None
                ):
                    results.append(mb.balanced[0]["balanced_target"].to_dict())
                else:
                    results.append(None)

            except Exception as e:
                # If an exception occurs, indicate failure
                warnings.warn(
                    f"Exception during feasibility check for target {target.get('name', 'Unnamed')}: {str(e)}",
                    stacklevel=2,
                )
                results.append(None)

        return results

    def apply_fixed_comps(self, target: dict) -> dict:
        """
        Apply fixed compositions to a target dictionary without overwriting existing values.

        Parameters
        ----------
        target : dict
            The target solution dictionary

        Returns
        -------
        dict
            A new target dictionary with fixed compositions applied
        """
        # Create a copy to avoid modifying the original
        result = target.copy()

        # Get fixed compositions from config
        fixed_comps = self.config.get("fixed_compositions", {})
        if not fixed_comps:
            return result

        # For each component property type that might exist in the target
        for prop_type in ["masses", "volumes", "concentrations", "mass_fractions"]:
            # Initialize property dictionaries if they don't exist
            if prop_type not in result:
                result[prop_type] = {}

            # If this property exists in fixed compositions
            if prop_type in fixed_comps:
                # Add each component from fixed compositions that doesn't already exist
                for comp_name, comp_value in fixed_comps[prop_type].items():
                    if comp_name not in result[prop_type]:
                        result[prop_type][comp_name] = comp_value

        # Handle simpler properties that might not be dictionaries
        for prop in ["total_mass", "total_volume", "name", "location"]:
            if prop in fixed_comps and prop not in result:
                result[prop] = fixed_comps[prop]

        # Handle solutes list
        if "solutes" in fixed_comps:
            if "solutes" not in result:
                result["solutes"] = fixed_comps["solutes"].copy()
            else:
                # Add any solutes that aren't already in the list
                for solute in fixed_comps["solutes"]:
                    if solute not in result["solutes"]:
                        result["solutes"].append(solute)

        return result

    def prepare(
        self, target: dict, dest: str | None = None
    ) -> tuple[dict, str] | tuple[None, None]:
        """Prepare the target solution. The dest argument is currently not used by this implementation."""
        # Apply fixed compositions without overwriting existing values
        target = self.apply_fixed_comps(target)

        # Check if the target is feasible before attempting preparation
        feasibility_results = self.is_feasible(target)
        if not feasibility_results or feasibility_results[0] is None:
            warnings.warn(
                f'Target composition {target.get("name", "Unnamed target")} is not feasible based on mass balance calculations',
                stacklevel=2,
            )
            return None, None

        balanced_target_dict_from_feasible = feasibility_results[0]

        self.reset_targets()
        # We need to re-add the original target, not the dict from is_feasible
        self.add_target(target)
        self.balance()

        if not self.balanced or not self.balanced[0].get("balanced_target"):
            warnings.warn(
                f'No suitable mass balance found for target: {target.get("name", "Unnamed target")}',
                stacklevel=2,
            )
            return None, None

        # This is the Solution object containing the protocol
        balanced_target_solution_object = self.balanced[0]["balanced_target"]

        # Configure the destination for the preparation
        if not self.config.get("mixing_locations"):
            raise ValueError(
                "No mixing locations configured. Cannot select a destination location."
            )

        # Pop a location from the mixing locations list
        if dest is None:
            # need to pop and then resend the locations list so that the persistant config triggers a write
            mixing_locations = self.config["mixing_locations"]
            destination = mixing_locations.pop(0)
            self.config["mixing_locations"] = mixing_locations
        else:
            destination = dest

        # Execute the protocol using OT2HTTPDriver
        if (
            not hasattr(balanced_target_solution_object, "protocol")
            or not balanced_target_solution_object.protocol
        ):
            raise ValueError("No protocol generated for the target solution")

        # Reorder protocol based on stock_mix_order if specified
        protocol = self.reorder_protocol(balanced_target_solution_object.protocol)

        # Execute each step in the protocol
        for step in protocol:
            # Get source and destination
            source = step.source
            dest = destination
            volume_ul = step.volume  # Volume is already in μL

            # Map source to a deck location
            if source not in self.config["stock_locations"]:
                raise ValueError(f"No deck location found for source: {source}")

            source_location = self.config["stock_locations"][source]

            # Get stock-specific transfer parameters
            transfer_params = self.get_transfer_params(source)

            # Execute the transfer
            try:
                self.transfer(
                    source=source_location,
                    dest=dest,
                    volume=volume_ul,
                    **transfer_params,
                )
            except Exception as e:
                warnings.warn(
                    f"Transfer failed from {source} to {dest}: {str(e)}", stacklevel=2
                )
                return None, None

        # Return the balanced target and destination
        return balanced_target_solution_object.to_dict(), destination

    def get_transfer_params(self, stock_name):
        """
        Get the transfer parameters for a specific stock solution.

        Parameters
        ----------
        stock_name : str
            Name of the stock solution

        Returns
        -------
        dict
            Dictionary of transfer parameters to pass to transfer()
        """
        # Get stock-specific parameters if available
        stock_params = self.config.get("stock_transfer_params", {}).get(stock_name, {})

        # Get default parameters
        default_params = self.config.get("stock_transfer_params", {}).get("default", {})

        # Combine default and stock-specific parameters, with stock-specific taking precedence
        params = default_params.copy()
        params.update(stock_params)

        return params

    @Driver.unqueued(render_hint="html")
    def configure_stocks(self, **kwargs):
        """Return an HTML interface for configuring stock solutions."""
        from importlib.resources import files
        from jinja2 import Template

        template_path = files("AFL.automation.driver_templates").joinpath(
            "ot2_prepare_stocks.html"
        )
        template = Template(template_path.read_text())
        html = template.render(
            stocks=self.config.get("stocks", []),
            stock_locations=self.config.get("stock_locations", {}),
        )
        return html

    @Driver.queued
    def add_stock(self, stock: Dict):
        """Add a stock definition and deck location."""
        import json

        if isinstance(stock, str):
            stock = json.loads(stock)

        location = stock.pop("location", None)

        # ensure a minimal volume if concentrations are given without any
        # volume information. This allows specifications like "20 mg/ml NaCl,
        # balance H2O" to be valid inputs.
        has_conc = bool(stock.get("concentrations"))
        has_volume = bool(stock.get("volumes")) or stock.get("total_volume")
        if has_conc and not has_volume:
            stock["total_volume"] = "1 ml"

        MassBalanceDriver.add_stock(self, stock)

        name = stock.get("name")
        if location and name:
            self.config["stock_locations"][name] = location

    @Driver.quickbar(qb={"button_text": "Reset Stocks"})
    def reset_stock_config(self):
        """Clear all configured stocks and locations."""
        MassBalanceDriver.reset_stocks(self)
        self.config["stock_locations"] = {}

    def reorder_protocol(self, protocol):
        """
        Reorder the protocol based on stock_mix_order if specified

        Parameters
        ----------
        protocol : list
            List of PipetteAction objects

        Returns
        -------
        list
            Reordered list of PipetteAction objects
        """
        # If no stock_mix_order is specified, return original protocol
        stock_mix_order = self.config.get("stock_mix_order", [])
        if not stock_mix_order:
            return protocol

        # Group protocol steps by source
        steps_by_source = {}
        for step in protocol:
            if step.source not in steps_by_source:
                steps_by_source[step.source] = []
            steps_by_source[step.source].append(step)

        # Build reordered protocol based on stock_mix_order
        reordered = []
        for stock_name in stock_mix_order:
            if stock_name in steps_by_source:
                reordered.extend(steps_by_source[stock_name])
                del steps_by_source[stock_name]

        # Add any remaining steps that weren't in stock_mix_order
        for steps in steps_by_source.values():
            reordered.extend(steps)

        return reordered

    def reset(self):
        """Reset the driver state/configuration."""
        # Placeholder: implement reset logic
        self.reset_targets()
        self.reset_stocks()


_DEFAULT_PORT = 5002
if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
