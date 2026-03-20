import threading
import time
from typing import Dict

import lazy_loader as lazy

from AFL.automation.prepare.PrepareDriver import PrepareDriver
from AFL.automation.shared.mock_eic_client import MockEICClient

epics = lazy.load("epics", require="AFL-automation[neutron-scattering]")


# Global list of driver commands to inject as no-ops.
NOOP_COMMANDS = [
    "transfer",
    "transfer_to_catch",
    "loadSample",
    "advanceSample",
    "calibrate_sensor",
    "home",
    "rinseCell",
]


def _noop(*args, **kwargs):
    """Default no-op handler for injected commands."""
    return None


def _inject_noop_methods(cls, command_names):
    """Inject no-op methods for any missing command names on the class."""
    for name in command_names:
        if not hasattr(cls, name):
            setattr(cls, name, _noop)


try:
    from AFL.automation.instrument.EICClient import EICClient
except ImportError:
    EICClient = None


class BioSANSPrepare(PrepareDriver):
    defaults = {
        "mixing_locations": [],
        "catch_volume": "10 ul",
        "exposure": 600,
        "cfenable_timeout_s": 1800.0,
        "stocks": [],
        "fixed_compositions": {},
        "eic_token": "1",
        "ipts_number": "1234",
        "beamline": "CG3",
        "mock_mode": False,
        "sample_equilibration_delay_s": 180,
    }

    def __init__(self, overrides=None):
        PrepareDriver.__init__(self, driver_name="BioSANSPrepare", overrides=overrides)
        self._client = None
        self.last_scan_id = None
        self.stock_pv_map = {}
        self._popped_destination = None

    def _status_lines(self):
        status = []
        status.append(f"BioSANS Stock PVs: {list(self.stock_pv_map.keys())}")
        status.append(f"{len(self.config['mixing_locations'])} mixing locations left")
        return status

    def before_balance(self, target: dict) -> None:
        if not self.config["mock_mode"]:
            timeout_s = float(self.config.get("cfenable_timeout_s", 1800.0))
            self._wait_for_cfenable_cycle(timeout_s=timeout_s)

    def resolve_destination(self, dest):
        self._popped_destination = None
        if dest is not None:
            return dest
        if not self.config.get("mixing_locations"):
            raise ValueError("No mixing locations configured. Cannot select a destination PV.")
        mixing_locations = self.config["mixing_locations"]
        destination = mixing_locations.pop(0)
        self.config["mixing_locations"] = mixing_locations
        self._popped_destination = destination
        return destination

    def on_prepare_exception(self, destination, dest_was_none):
        if dest_was_none and self._popped_destination is not None:
            mixing_locations = self.config["mixing_locations"]
            mixing_locations.insert(0, self._popped_destination)
            self.config["mixing_locations"] = mixing_locations
            self._popped_destination = None

    def execute_preparation(self, target: dict, balanced_target, destination: str) -> bool:
        self.make_stock_pv_map()

        stock_volumes = {f"CG3:SE:CMP:S{i}Vol": 0 for i in range(1, 9)}
        for pipette_action in balanced_target.protocol:
            source_stock_name = pipette_action.source
            if source_stock_name not in self.stock_pv_map:
                raise ValueError(
                    f"Stock PV for '{source_stock_name}' not found in stock_pv_map. "
                    f"Available stocks in map: {list(self.stock_pv_map.keys())}"
                )
            stock_volumes[self.stock_pv_map[source_stock_name]] = pipette_action.volume

        catch_volume = self.config.get("catch_volume")
        if catch_volume is None:
            raise ValueError("Catch volume ('catch_volume') is not configured.")

        target_name = target.get("name", "Unnamed target")
        headers = [
            "Title",
            "CG3:SE:CMP:S1Vol",
            "CG3:SE:CMP:S2Vol",
            "CG3:SE:CMP:S3Vol",
            "CG3:SE:CMP:S4Vol",
            "CG3:SE:CMP:S5Vol",
            "CG3:SE:CMP:S6Vol",
            "CG3:SE:CMP:S7Vol",
            "CG3:SE:CMP:S8Vol",
            "CG3:SE:URMPI:143",
            "CG3:SE:URPI:MixFinalVolume",
            "CG3:SE:URPI:ChangeTips",
            "RobotProcess",
            "URMPI147Wait",
            "Delay",
            "CG3:Mot:AttnPos:Menu",
            "Wait For",
            "Value",
            "CG3:Mot:AttnPos:Menu",
        ]
        row = [
            target_name,
            stock_volumes["CG3:SE:CMP:S1Vol"],
            stock_volumes["CG3:SE:CMP:S2Vol"],
            stock_volumes["CG3:SE:CMP:S3Vol"],
            stock_volumes["CG3:SE:CMP:S4Vol"],
            stock_volumes["CG3:SE:CMP:S5Vol"],
            stock_volumes["CG3:SE:CMP:S6Vol"],
            stock_volumes["CG3:SE:CMP:S7Vol"],
            stock_volumes["CG3:SE:CMP:S8Vol"],
            destination,
            catch_volume,
            0,
            1,
            1,
            self.config["sample_equilibration_delay_s"],
            2,
            "seconds",
            self.config["exposure"],
            6,
        ]

        success, self.last_scan_id, response_data = self.client.submit_table_scan(
            parms={"run_mode": 0, "headers": headers, "rows": [row]},
            desc=f"AFL prepare table scan for {target_name}",
            simulate_only=False,
        )
        if not success:
            raise RuntimeError(f"Error in EIC table scan: {response_data}")

        self.blockForTableScan()

        rinse_headers = [
            "Title",
            "CG3:SE:URMPI:Mom144",
            "CG3:SE:CMP:CFEnable",
            "Delay",
            "URMPI145Wait",
            "CG3:SE:CMP:CFEnable",
        ]
        rinse_row = ["Clean cell and measure MT cell", 1, 1, 5, 1, 0]
        self.client.submit_table_scan(
            parms={"run_mode": 0, "headers": rinse_headers, "rows": [rinse_row]},
            desc="AFL rinse cell table scan",
            simulate_only=False,
        )
        return True

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
        self.reset_targets()
        self.reset_stocks()
        self.stocks = []
        self.targets = []

    @property
    def client(self):
        if self._client is None:
            if self.config["mock_mode"]:
                self._client = MockEICClient(
                    ipts_number=str(self.config["ipts_number"]),
                    eic_token=self.config["eic_token"],
                    beamline=self.config["beamline"],
                )
            else:
                if EICClient is None:
                    raise ImportError("eic_client is not available and mock_mode is False")
                self._client = EICClient(
                    ipts_number=str(self.config["ipts_number"]),
                    eic_token=self.config["eic_token"],
                    beamline=self.config["beamline"],
                )
        return self._client

    def make_stock_pv_map(self):
        self.stock_pv_map = {}
        self.process_stocks()

        desc_to_pv: Dict[str, str] = {}
        for i in range(8):
            pv_name = f"CG3:SE:CMP:S{i+1}Vol"
            stock_desc = str(self.get_pv(pv_name + ".DESC")).strip()
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

    def set_pv(self, pv_name, value, timeout=10, wait=True):
        success_set, response_data_set = self.client.set_pv(pv_name, value, timeout, wait)
        if not success_set:
            raise ValueError(f"Failed to set PV {pv_name}")

    def get_pv(self, pv_name, timeout=10):
        success_get, pv_value_read, response_data_get = self.client.get_pv(pv_name, timeout)
        if not success_get:
            raise ValueError(f"Failed to get PV {pv_name}: {response_data_get}")
        return pv_value_read


_inject_noop_methods(BioSANSPrepare, NOOP_COMMANDS)

_DEFAULT_PORT = 5002
if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
