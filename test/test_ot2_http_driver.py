import pytest

from AFL.automation.prepare.OT2HTTPDriver import OT2HTTPDriver


class DummyConfig(dict):
    def _update_history(self):
        return None


class StubOT2HTTPDriver(OT2HTTPDriver):
    def __init__(self):
        self.app = None
        self.config = DummyConfig({
            "loaded_instruments": {},
            "loaded_labware": {},
            "available_tips": {},
            "loaded_modules": {},
        })
        self.data = {}
        self.session_id = None
        self.protocol_id = None
        self.run_id = "test-run"
        self.max_transfer = None
        self.min_transfer = None
        self.min_largest_pipette = None
        self.max_smallest_pipette = None
        self.has_tip = False
        self.last_pipette = None
        self.modules = {}
        self.pipette_info = {}
        self.hardware_pipettes = {}
        self.executed_commands = []

    def _ensure_run_exists(self, check_run_status=True):
        return self.run_id

    def _update_pipettes(self):
        self.pipette_info = {
            mount: info.copy() for mount, info in self.hardware_pipettes.items()
        }
        self.min_transfer = None
        self.max_transfer = None

        for info in self._get_active_pipettes().values():
            min_volume = info.get("min_volume")
            max_volume = info.get("max_volume")

            if self.min_transfer is None or self.min_transfer > min_volume:
                self.min_transfer = min_volume
            if self.max_transfer is None or self.max_transfer < max_volume:
                self.max_transfer = max_volume

    def get_wells(self, location):
        return [{"labwareId": "labware_1", "wellName": location[-2:]}]

    def _execute_atomic_command(self, command, params, check_run_status=True):
        if command == "pickUpTip":
            mount = params["pipetteMount"]
            self.get_tip(mount)
            self.has_tip = True
            self.last_pipette = mount
        elif command == "dropTipInPlace":
            self.has_tip = False

        self.executed_commands.append((command, dict(params)))
        return {"commandType": command, "params": params}


def _pipette_info(mount, pipette_id, *, min_volume, max_volume):
    return {
        "id": pipette_id,
        "name": f"p{max_volume}_single",
        "model": f"p{max_volume}_single_v1",
        "serial": f"{mount}-serial",
        "mount": mount,
        "min_volume": min_volume,
        "max_volume": max_volume,
        "aspirate_flow_rate": 150,
        "dispense_flow_rate": 300,
        "channels": 1,
    }


def _configured_driver():
    driver = StubOT2HTTPDriver()
    driver.hardware_pipettes = {
        "left": _pipette_info("left", "left-id", min_volume=20, max_volume=300),
        "right": _pipette_info("right", None, min_volume=1, max_volume=100),
    }
    driver.config["loaded_instruments"]["left"] = {
        "name": "p300_single",
        "pipette_id": "left-id",
        "tip_racks": ["tiprack-left"],
    }
    driver.config["available_tips"]["left"] = [
        ("tiprack-left", "A1"),
        ("tiprack-left", "A2"),
    ]
    driver._update_pipettes()
    driver._update_pipette_ranges()
    return driver


def test_set_flow_rates_updates_only_loaded_pipettes():
    driver = _configured_driver()

    driver.set_aspirate_rate(111)
    driver.set_dispense_rate(222)

    assert driver.pipette_info["left"]["aspirate_flow_rate"] == 111
    assert driver.pipette_info["left"]["dispense_flow_rate"] == 222
    assert driver.pipette_info["right"]["aspirate_flow_rate"] == 150
    assert driver.pipette_info["right"]["dispense_flow_rate"] == 300


def test_get_pipette_ignores_attached_but_unloaded_mount():
    driver = _configured_driver()

    pipette = driver.get_pipette(50)

    assert pipette["mount"] == "left"
    assert pipette["pipette_id"] == "left-id"


def test_transfer_with_single_loaded_pipette_allows_rate_overrides():
    driver = _configured_driver()

    driver.transfer("1A1", "1A2", 50, aspirate_rate=111, dispense_rate=222)

    command_names = [name for name, _ in driver.executed_commands]
    assert "pickUpTip" in command_names
    assert "aspirate" in command_names
    assert "dispense" in command_names
    assert "dropTipInPlace" in command_names
    assert driver.last_pipette == "left"


def test_get_pipette_raises_when_no_loaded_pipettes_exist():
    driver = StubOT2HTTPDriver()
    driver.hardware_pipettes = {
        "left": _pipette_info("left", None, min_volume=20, max_volume=300),
    }

    with pytest.raises(ValueError, match="No suitable loaded pipettes found!"):
        driver.get_pipette(50)


def test_pipette_ranges_ignore_unloaded_mounts():
    driver = _configured_driver()

    assert driver.min_largest_pipette == 20
    assert driver.max_smallest_pipette == 300
