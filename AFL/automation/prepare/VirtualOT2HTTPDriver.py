import uuid
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import listify
from AFL.automation.prepare.OT2HTTPDriver import OT2HTTPDriver, TIPRACK_WELLS


class VirtualOT2HTTPDriver(OT2HTTPDriver):
    """In-memory mock of :class:`OT2HTTPDriver` for CI testing.

    This driver inherits from :class:`OT2HTTPDriver` but overrides all
    network-facing functionality. Calls simply update internal state and
    log actions, allowing test suites to exercise OT2-dependent code without
    requiring hardware or the HTTP server.
    """

    def __init__(self, overrides=None):
        super().__init__(overrides=overrides)
        self.name = "VirtualOT2HTTPDriver"
        self.reset()

    # ------------------------------------------------------------------
    # Internal helpers
    def _initialize_robot(self):
        """Skip hardware initialization and prepare empty state."""
        self.pipette_info = {}
        self.available_tips = {}
        self.min_transfer = None
        self.max_transfer = None
        self.log_info("Initialized virtual OT2 robot")

    def _update_pipettes(self):
        """Update cached pipette info from loaded instruments."""
        self.min_transfer = None
        self.max_transfer = None
        for mount, info in self.pipette_info.items():
            if not info:
                continue
            min_v = info.get("min_volume", 1)
            max_v = info.get("max_volume", 1000)
            if self.min_transfer is None or self.min_transfer > min_v:
                self.min_transfer = min_v
            if self.max_transfer is None or self.max_transfer < max_v:
                self.max_transfer = max_v

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    def reset(self):
        """Reset all stored state."""
        self.session_id = "virtual"
        self.protocol_id = "virtual"
        self.loaded_labware = {}
        self.loaded_instruments = {}
        self.loaded_modules = {}
        self.available_tips = {}
        self.pipette_info = {}
        self.has_tip = False
        self.last_pipette = None
        self.log_info("Virtual OT2 reset")

    # ------------------------------------------------------------------

    @Driver.quickbar(qb={"button_text": "Home"})
    def home(self, **kwargs):
        self.log_info("Virtual home executed")

    def load_labware(self, name, slot, module=None, **kwargs):
        labware_id = self._generate_id("labware")
        definition = {
            "definition": {
                "wells": {w: {} for w in TIPRACK_WELLS},
                "metadata": {"displayName": name},
            }
        }
        self.loaded_labware[str(slot)] = (labware_id, name, definition)
        self.log_info(f"Loaded labware {name} into slot {slot} with id {labware_id}")
        return labware_id

    def load_instrument(self, name, mount, tip_rack_slots, **kwargs):
        pipette_id = self._generate_id("pipette")
        tip_racks = [self.loaded_labware[str(s)][0] for s in listify(tip_rack_slots)]
        self.loaded_instruments[mount] = {
            "name": name,
            "pipette_id": pipette_id,
            "tip_racks": tip_racks,
        }
        self.available_tips[mount] = []
        for rack in tip_racks:
            for well in TIPRACK_WELLS:
                self.available_tips[mount].append((rack, well))
        self.pipette_info[mount] = {
            "id": pipette_id,
            "name": name,
            "min_volume": 1,
            "max_volume": 1000,
            "aspirate_flow_rate": 150,
            "dispense_flow_rate": 300,
        }
        self._update_pipettes()
        self.log_info(f"Loaded instrument {name} on {mount} with id {pipette_id}")
        return pipette_id

    # ------------------------------------------------------------------
    def pick_up_tip(self, mount):
        if self.has_tip:
            self.log_warning("Tip already picked up")
            return
        if mount not in self.available_tips or not self.available_tips[mount]:
            raise RuntimeError(f"No tips available on {mount} mount")
        tiprack_id, well = self.available_tips[mount].pop(0)
        self.has_tip = True
        self.last_pipette = mount
        self.log_info(f"Picked up tip from {tiprack_id} well {well} on {mount}")

    def drop_tip(self, mount):
        if not self.has_tip:
            self.log_warning("No tip to drop")
            return
        self.has_tip = False
        self.log_info(f"Dropped tip from {mount}")

    @Driver.quickbar(
        qb={
            "button_text": "Transfer",
            "params": {
                "source": {"label": "Source Well", "type": "text", "default": "1A1"},
                "dest": {"label": "Dest Well", "type": "text", "default": "1A1"},
                "volume": {"label": "Volume (uL)", "type": "float", "default": 300},
            },
        }
    )
    def transfer(self, source, dest, volume, drop_tip=True, **kwargs):
        mount = next(iter(self.loaded_instruments.keys()))
        self.pick_up_tip(mount)
        self.log_info(f"Aspirating {volume}uL from {source}")
        self.log_info(f"Dispensing {volume}uL to {dest}")
        if drop_tip:
            self.drop_tip(mount)



if __name__ == "__main__":
    from AFL.automation.shared.launcher import *

