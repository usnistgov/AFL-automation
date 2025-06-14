import warnings
import time
from typing import List, Union, Dict, Any
from AFL.automation.mixing.MassBalance import MassBalanceDriver, MassBalance
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import listify
from eic_client.EICClient import EICClient

class BioSANSPrepare(MassBalanceDriver, Driver):
    defaults = {
        'mixing_locations': [],
        'prepare_volume': '100 ul',
        'catch_volume': '10 ul',
        'deck': {},
        'stocks': [],
        'stock_mix_order': [],
        'fixed_compositions': {},
        'eic_token': '1',
        'ipts_number': '1234',
        'beamline': 'CG3',
    }

    def __init__(self, overrides=None):
        Driver.__init__(self, name='BioSANSPrepare', defaults=self.gather_defaults(), overrides=overrides)
        self._client = None
        self.stock_pv_map = {}
        self.stocks = []
        self.targets = []
    
    def status(self):
        """
        Get the status of the BioSANSPrepareDriver.
        """
        status = []
        status.append(f'Stocks: {self.config["stocks"]}')
        status.append(f'Stocks on BioSANS: {list(self.stock_pv_map.keys())}')
        status.append(f'{len(self.config["mixing_locations"])} mixing locations left')
        return status
            

    def is_feasible(self, targets: dict |  list[dict]) -> list[dict | None]:
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
        minimum_volume = self.config.get('minimum_volume', '100 ul')
        
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
                mb.balance(tol=self.config.get('tol', 1e-3))
                
                # Check if balance was successful for this target
                if (mb.balanced and 
                    len(mb.balanced) > 0 and 
                    mb.balanced[0].get('balanced_target') is not None):
                    results.append(mb.balanced[0]['balanced_target'].to_dict())
                else:
                    results.append(None)
                    
            except Exception as e:
                # If an exception occurs, indicate failure
                warnings.warn(f"Exception during feasibility check for target {target.get('name', 'Unnamed')}: {str(e)}", stacklevel=2)
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
        fixed_comps = self.config.get('fixed_compositions', {})
        if not fixed_comps:
            return result
            
        # For each component property type that might exist in the target
        for prop_type in ['masses', 'volumes', 'concentrations', 'mass_fractions']:
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
        for prop in ['total_mass', 'total_volume', 'name', 'location']:
            if prop in fixed_comps and prop not in result:
                result[prop] = fixed_comps[prop]
                
        # Handle solutes list
        if 'solutes' in fixed_comps:
            if 'solutes' not in result:
                result['solutes'] = fixed_comps['solutes'].copy()
            else:
                # Add any solutes that aren't already in the list
                for solute in fixed_comps['solutes']:
                    if solute not in result['solutes']:
                        result['solutes'].append(solute)
                        
        return result

    def prepare(self, target: dict, dest: str | None = None) -> tuple[dict, str] | tuple[None, None]:
        """Prepare the target solution. The dest argument is currently not used by this implementation."""
        # Apply fixed compositions without overwriting existing values
        target = self.apply_fixed_comps(target)

        # Check if the target is feasible before attempting preparation
        feasibility_results = self.is_feasible(target)
        if not feasibility_results or feasibility_results[0] is None:
            warnings.warn(f'Target composition {target.get("name", "Unnamed target")} is not feasible based on mass balance calculations', stacklevel=2)
            return None, None

        balanced_target_dict_from_feasible = feasibility_results[0]

        self.reset_targets()
        # We need to re-add the original target, not the dict from is_feasible
        self.add_target(target) 
        self.balance()

        if not self.balanced or not self.balanced[0].get('balanced_target'):
            warnings.warn(f'No suitable mass balance found for target: {target.get("name", "Unnamed target")}',stacklevel=2)
            return None, None
        
        # This is the Solution object containing the protocol
        balanced_target_solution_object = self.balanced[0]['balanced_target']
        
        self.make_stock_pv_map()

        # Configure the destination for the preparation
        if not self.config.get('mixing_locations'):
            raise ValueError("No mixing locations configured. Cannot select a destination PV.")
        
        # Pop the PV name that will be used to select the specific mixing destination/station
        # Its value will be set to the actual target vial PV "CG3:SE:URMPI:143"
        if dest is None:
            # need to pop and then resend the locations list so that the persistant config triggers a write
            mixing_locations = self.config['mixing_locations']
            destination = mixing_locations.pop(0)
            self.config['mixing_locations'] = mixing_locations
        else:
            destination = dest
        try:
            self.set_pv("CG3:SE:URMPI:143",destination)
        except Exception as e:
            # If setting fails, put it back in the list if possible, though state might be inconsistent
            self.config['mixing_locations'].insert(0, destination)
            raise ValueError(f"Failed to set destination PV {destination} to CG3:SE:URMPI:143: {e}")

        # Configure the catch volume for the mixing process
        catch_volume_value = self.config.get('catch_volume')
        if catch_volume_value is None:
            raise ValueError("Catch volume ('catch_volume') is not configured.")
        try:
            self.set_pv("CG3:SE:URPI:MixFinalVolume", catch_volume_value)
        except Exception as e:
            raise ValueError(f"Failed to set catch volume PV CG3:SE:URPI:MixFinalVolume to {catch_volume_value}: {e}")

        # Validate that all source stocks in the protocol have PVs mapped
        for pipette_action in balanced_target_solution_object.protocol:
            source_stock_name = pipette_action.source
            if source_stock_name not in self.stock_pv_map:
                raise ValueError(
                    f"Stock PV for '{source_stock_name}' not found in stock_pv_map. "
                    f"Available stocks in map: {list(self.stock_pv_map.keys())}"
                )
            self.set_pv(self.stock_pv_map[source_stock_name], pipette_action.volume)

        # Start the automated mixing process
        try:
            self.set_pv("CG3:SE:CMP:StartProcess", 1)
        except Exception as e:
            raise RuntimeError(f"Failed to start process by setting CG3:SE:CMP:StartProcess: {e}")

        # Wait for the process to complete
        time.sleep(5.0) # Pause before checking busy status
        while True:
            time.sleep(1.0) # Pause before checking busy status
            try:
                busy_status = self.get_pv("CG3:SE:CMP:Busy")
                # PVs can return strings, ensure comparison is robust
                if str(busy_status).strip() == "0":
                    break 
            except Exception as e:
                warnings.warn(f"Could not get busy status from CG3:SE:CMP:Busy (continuing to wait): {e}")
                # Decide on retry strategy or eventually timing out if necessary

        return balanced_target_dict_from_feasible, destination
        

    def transfer(self,*args,**kwargs):
        """Transfer a specified volume from src to dest."""
        pass

    def loadSample(self,*args,**kwargs):
        """Load a sample into the driver."""
        pass

    def rinseCell(self,*args,**kwargs):
        """Load a sample into the driver."""
        pass


    def reset(self):
        """Reset the driver state/configuration."""
        # Placeholder: implement reset logic
        self.reset_targets()
        self.reset_stocks()

    @property
    def client(self):
        """
        Property that returns the EIC client instance.
        
        If the client doesn't exist yet, it instantiates a new EICClient
        using the token and beamline from the configuration.
        
        Returns
        -------
        EICClient
            The client instance for communicating with the instrument.
        """
        if self._client is None:
            self._client = EICClient(
                ipts_number=self.config['ipts_number'],
                eic_token=self.config['eic_token'],
                beamline=self.config['beamline']
            )
        return self._client
    
    def make_stock_pv_map(self):
        """
        Make a map of the stock locations to the stock solutions.
        """
        self.stock_pv_map = {}

        num_stocks = 8
        for i in range(num_stocks):
            pv_name = f'CG3:SE:CMP:S{i+1}Vol'
            stock_name = self.get_pv(pv_name + '.DESC')
            self.stock_pv_map[stock_name] = pv_name
    
    def set_pv(self, pv_name, value,timeout=10,wait=True):
        success_set, response_data_set = self.client.set_pv(pv_name, value,timeout,wait)
        if not success_set:
            raise ValueError(f'Failed to set PV {pv_name}')

    def get_pv(self, pv_name, timeout=10):
        success_get, pv_value_read, response_data_get = self.client.get_pv(pv_name, timeout)
        if not success_get:
            raise ValueError(f'Failed to get PV {pv_name}: {response_data_get}')
        return pv_value_read


_DEFAULT_PORT=5002
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *

    
