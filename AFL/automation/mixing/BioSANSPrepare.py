import warnings
import time
import threading
from typing import List, Union, Dict, Any
from AFL.automation.mixing.MassBalance import MassBalance
from AFL.automation.mixing.MassBalanceDriver import MassBalanceDriver
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import listify
from AFL.automation.shared.mock_eic_client import MockEICClient
from AFL.automation.shared.PersistentConfig import PersistentConfig
import lazy_loader as lazy
epics = lazy.load("epics", require="AFL-automation[neutron-scattering]")


# Global list of driver commands to inject as no-ops.
NOOP_COMMANDS = [
    'transfer',
    'transfer_to_catch',
    'loadSample',
    'advanceSample',
    'calibrate_sensor',
    'home',
    'rinseCell',
]


def _noop(*args, **kwargs):
    """Default no-op handler for injected commands."""
    return None


def _inject_noop_methods(cls, command_names):
    """Inject no-op methods for any missing command names on the class."""
    for name in command_names:
        if not hasattr(cls, name):
            setattr(cls, name, _noop)


# Optional import for EIC client
try:
    from eic_client.EICClient import EICClient
except ImportError:
    EICClient = None


class BioSANSPrepare(MassBalanceDriver):
    defaults = {
        'mixing_locations': [],
        'catch_volume': '10 ul',
        'exposure': 600,
        'cfenable_timeout_s': 1800.0,
        'stocks': [],
        'fixed_compositions': {},
        'eic_token': '1',
        'ipts_number': '1234',
        'beamline': 'CG3',
        'mock_mode': False,
    }

    def __init__(self, overrides=None):
        MassBalanceDriver.__init__(self, overrides=overrides,)

        self.name = 'BioSANSPrepare'
        self.filepath = self.path / (self.name + '.config.json')

        self.config = PersistentConfig(
            path=self.filepath,
            defaults=self.gather_defaults(),
            overrides=overrides,
            max_history=100,
            max_history_size_mb=50,
            write_debounce_seconds=0.5,
            compact_json=True,
        )

        self._client = None
        self.last_scan_id = None
        self.stock_pv_map = {}
        self.stocks = self.config.get('stocks', [])
        self.targets = []
        self.process_stocks()
    
    def status(self):
        """
        Get the status of the BioSANSPrepareDriver.
        """
        status = []
        status.append(f'AFL Server Stocks: {self.config["stocks"]}')
        status.append(f'BioSANS Stock PVs: {list(self.stock_pv_map.keys())}')
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
            
        # Always process stocks from config to avoid stale in-memory state.
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

        if not self.config['mock_mode']:
            timeout_s = float(self.config.get('cfenable_timeout_s', 1800.0))
            self._wait_for_cfenable_cycle(timeout_s=timeout_s)

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
        if dest is None:
            # need to pop and then resend the locations list so that the persistant config triggers a write
            mixing_locations = self.config['mixing_locations']
            destination = mixing_locations.pop(0)
            self.config['mixing_locations'] = mixing_locations
            popped_destination = True
        else:
            destination = dest
            popped_destination = False

        try:
            # Build stock volumes dict defaulting all 8 slots to 0
            stock_volumes = {f'CG3:SE:CMP:S{i}Vol': 0 for i in range(1, 9)}

            # Fill non-zero values from balanced_target protocol using stock_pv_map
            for pipette_action in balanced_target_solution_object.protocol:
                source_stock_name = pipette_action.source
                if source_stock_name not in self.stock_pv_map:
                    raise ValueError(
                        f"Stock PV for '{source_stock_name}' not found in stock_pv_map. "
                        f"Available stocks in map: {list(self.stock_pv_map.keys())}"
                    )
                stock_volumes[self.stock_pv_map[source_stock_name]] = pipette_action.volume

            catch_volume = self.config.get('catch_volume')
            if catch_volume is None:
                raise ValueError("Catch volume ('catch_volume') is not configured.")

            target_name = target.get('name', 'Unnamed target')

            headers = [
                'Title',
                'CG3:SE:CMP:S1Vol', 'CG3:SE:CMP:S2Vol', 'CG3:SE:CMP:S3Vol', 'CG3:SE:CMP:S4Vol',
                'CG3:SE:CMP:S5Vol', 'CG3:SE:CMP:S6Vol', 'CG3:SE:CMP:S7Vol', 'CG3:SE:CMP:S8Vol',
                'CG3:SE:URMPI:143', 'CG3:SE:URPI:MixFinalVolume', 'CG3:SE:URPI:ChangeTips',
                'RobotProcess', 'URMPI147Wait', 'Delay', 'Wait For', 'Value',
            ]
            row = [
                target_name,
                stock_volumes['CG3:SE:CMP:S1Vol'], stock_volumes['CG3:SE:CMP:S2Vol'],
                stock_volumes['CG3:SE:CMP:S3Vol'], stock_volumes['CG3:SE:CMP:S4Vol'],
                stock_volumes['CG3:SE:CMP:S5Vol'], stock_volumes['CG3:SE:CMP:S6Vol'],
                stock_volumes['CG3:SE:CMP:S7Vol'], stock_volumes['CG3:SE:CMP:S8Vol'],
                destination, catch_volume, 1,
                1, 1, 5, 'seconds', self.config['exposure'],
            ]

            success, self.last_scan_id, response_data = self.client.submit_table_scan(
                parms={
                    'run_mode': 0,
                    'headers': headers,
                    'rows': [row],
                },
                desc=f'AFL prepare table scan for {target_name}',
                simulate_only=False,
            )
            if not success:
                raise RuntimeError(f'Error in EIC table scan: {response_data}')

            self.blockForTableScan()

            # Submit rinse/MT-cell scan immediately after measurement, but don't block
            # rinse_headers = [
            #     'Title', 'CG3:SE:URMPI:Mom144', 'CG3:SE:CMP:CFEnable', 'Delay',
            #     'URMPI145Wait', 'CG3:SE:CMP:CFEnable', 'Wait For', 'Value',
            # ]
            # rinse_row = ['Clean cell and measure MT cell', 1, 1, 5, 1, 0, 'seconds', 10]

            # Submit rinse/MT-cell scan immediately after measurement, but don't block
            rinse_headers = [
                'Title', 'CG3:SE:URMPI:Mom144', 'CG3:SE:CMP:CFEnable', 'Delay',
                'URMPI145Wait', 'CG3:SE:CMP:CFEnable'
            ]
            rinse_row = ['Clean cell and measure MT cell', 1, 1, 5, 1, 0]
            self.client.submit_table_scan(
                parms={
                    'run_mode': 0,
                    'headers': rinse_headers,
                    'rows': [rinse_row],
                },
                desc='AFL rinse cell table scan',
                simulate_only=False,
            )

        except Exception:
            if popped_destination:
                mixing_locations = self.config['mixing_locations']
                mixing_locations.insert(0, destination)
                self.config['mixing_locations'] = mixing_locations
            raise

        return balanced_target_dict_from_feasible, destination

    def blockForTableScan(self):
        """Block until the last submitted table scan is complete."""
        status_success, is_done, state, status_response_data = self.client.get_scan_status(self.last_scan_id)
        while not is_done:
            time.sleep(0.1)
            status_success, is_done, state, status_response_data = self.client.get_scan_status(self.last_scan_id)

    def _wait_for_cfenable_cycle(self, timeout_s: float) -> None:
        pv_name = "CG3:SE:CMP:CFEnable"
        start_wait = time.monotonic()
        low_event = threading.Event()

        def _on_change(value=None, **_kwargs):
            try:
                v = int(value)
            except Exception:
                return
            if v == 0:
                low_event.set()

        pv = None
        callback_index = None
        try:
            pv = epics.PV(pv_name)
            callback_index = pv.add_callback(_on_change)

            try:
                current = pv.get()
            except Exception as e:
                raise RuntimeError(f"Failed to read {pv_name}: {e}")

            try:
                current_int = int(current)
            except Exception:
                current_int = None

            elapsed = time.monotonic() - start_wait
            remaining = max(0.0, timeout_s - elapsed)
            if remaining == 0.0:
                raise TimeoutError(f"Timed out waiting for {pv_name} cycle after {timeout_s} seconds")

            if current_int == 1:
                # Already high: wait for it to drop to 0
                if not low_event.wait(timeout=remaining):
                    raise TimeoutError(f"Timed out waiting for {pv_name} to drop after {timeout_s} seconds")
                return

            if current_int == 0:
                return

            raise RuntimeError(f"Unexpected value for {pv_name}: {current}")
        finally:
            if pv is not None:
                if callback_index is not None:
                    try:
                        pv.remove_callback(callback_index)
                    except Exception:
                        pass
                try:
                    pv.disconnect()
                except Exception:
                    pass
        

    def reset(self):
        """Reset the driver state/configuration."""
        # Placeholder: implement reset logic
        self.reset_targets()
        self.reset_stocks()
        self.stocks = []
        self.targets = []

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
            if self.config['mock_mode']:
                self._client = MockEICClient(
                    ipts_number=str(self.config['ipts_number']),
                    eic_token=self.config['eic_token'],
                    beamline=self.config['beamline']
                )
            else:
                if EICClient is None:
                    raise ImportError("eic_client is not available and mock_mode is False")
                self._client = EICClient(
                    ipts_number=str(self.config['ipts_number']),
                    eic_token=self.config['eic_token'],
                    beamline=self.config['beamline']
                )
        return self._client
    
    def make_stock_pv_map(self):
        """
        Make a map of the stock locations to the stock solutions.
        """
        self.stock_pv_map = {}

        self.process_stocks()

        num_stocks = 8
        desc_to_pv = {}
        for i in range(num_stocks):
            pv_name = f'CG3:SE:CMP:S{i+1}Vol'
            stock_desc = str(self.get_pv(pv_name + '.DESC')).strip()
            if stock_desc:
                desc_to_pv[stock_desc] = pv_name
                self.stock_pv_map[stock_desc] = pv_name

        for stock in self.stocks:
            pv_name = desc_to_pv.get(stock.name)
            if pv_name is None:
                continue
            if stock.location is not None:
                self.stock_pv_map[str(stock.location)] = pv_name
            self.stock_pv_map[str(stock.name)] = pv_name
    
    def set_pv(self, pv_name, value,timeout=10,wait=True):
        success_set, response_data_set = self.client.set_pv(pv_name, value,timeout,wait)
        if not success_set:
            raise ValueError(f'Failed to set PV {pv_name}')

    def get_pv(self, pv_name, timeout=10):
        success_get, pv_value_read, response_data_get = self.client.get_pv(pv_name, timeout)
        if not success_get:
            raise ValueError(f'Failed to get PV {pv_name}: {response_data_get}')
        return pv_value_read


_inject_noop_methods(BioSANSPrepare, NOOP_COMMANDS)

_DEFAULT_PORT=5002
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *



    
