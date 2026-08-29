import pytest
from pathlib import Path
import json
import logging
import threading
from types import SimpleNamespace

import numpy as np
import requests

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
            "reserved_stock_tips": [],
            "occupied_sample_locations": [],
            "loaded_modules": {},
            "tip_rack_offset": {"x": 0, "y": 0, "z": 0},
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
        self.current_tip = None
        self.modules = {}
        self.pipette_info = {}
        self.hardware_pipettes = {}
        self.executed_commands = []
        self.custom_labware_files = {}
        self.sent_custom_labware = {}
        self.custom_labware_dir = Path("/tmp/ot2-http-driver-tests")
        self.headers = {"Opentrons-Version": "2"}
        self.base_url = "http://ot2.test"

    def _ensure_run_exists(self, check_run_status=True):
        return self.run_id

    def _update_pipettes(self):
        self.pipette_info = {
            mount: info.copy() for mount, info in self.hardware_pipettes.items()
        }

    def get_wells(self, location):
        return [{"labwareId": "labware_1", "wellName": location[-2:]}]

    def _execute_atomic_command(self, command, params, check_run_status=True):
        if command == "pickUpTip":
            mount = params.get("pipetteMount", self.last_pipette)
            if "labwareId" in params and "wellName" in params:
                tiprack_id, well = self._reserve_tip(mount, params["labwareId"], params["wellName"])
            else:
                tiprack_id, well = self.get_tip(mount)
                params["labwareId"] = tiprack_id
                params["wellName"] = well
            pickup_offset = self._resolve_tip_rack_offset(params.get("tipRackOffset"))
            approach_offset = dict(pickup_offset)
            approach_offset["z"] = max(approach_offset.get("z", 0), 0)
            self.executed_commands.append((
                "moveToWell",
                {
                    "pipetteId": params["pipetteId"],
                    "labwareId": tiprack_id,
                    "wellName": well,
                    "wellLocation": {
                        "origin": "top",
                        "offset": approach_offset,
                    },
                },
            ))
            params["wellLocation"] = {
                "origin": "top",
                "offset": pickup_offset,
            }
            params.pop("tipRackOffset", None)
            self.has_tip = True
            self.last_pipette = mount
            self.current_tip = {
                "mount": mount,
                "labware_id": tiprack_id,
                "well_name": well,
            }
        elif command == "dropTipInPlace":
            self.has_tip = False
            self.current_tip = None

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
    driver.config["loaded_labware"]["1"] = (
        "tiprack-left",
        "opentrons_96_tiprack_300ul",
        {"definition": {"wells": {"A1": {}, "A2": {}, "A3": {}}}},
    )
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


def _custom_labware_def(
    z_value=6.1,
    *,
    load_name="nist_6_20ml_vials",
    namespace="custom_beta",
    is_tiprack=False,
    display_category="wellPlate",
):
    return {
        "ordering": [["A1", "B1"], ["A2", "B2"], ["A3", "B3"]],
        "brand": {"brand": "NIST", "brandId": ["gvh2"]},
        "metadata": {
            "displayName": "NIST 6 x 20 mL vial holder",
            "displayCategory": display_category,
            "displayVolumeUnits": "uL",
            "tags": [],
        },
        "dimensions": {"xDimension": 127.75, "yDimension": 85.5, "zDimension": 61.6},
        "wells": {
            well: {
                "depth": 56.5,
                "totalLiquidVolume": 20000,
                "shape": "circular",
                "diameter": 28.95,
                "x": x,
                "y": y,
                "z": z_value,
            }
            for well, x, y in (
                ("A1", 23, 62.5),
                ("B1", 23, 22.37),
                ("A2", 63.13, 62.5),
                ("B2", 63.13, 22.37),
                ("A3", 103.26, 62.5),
                ("B3", 103.26, 22.37),
            )
        },
        "groups": [
            {
                "metadata": {
                    "displayName": "NIST 6 x 20 mL vial holder",
                    "displayCategory": "wellPlate",
                    "wellBottomShape": "flat",
                },
                "brand": {"brand": "NIST", "brandId": ["gvh2"]},
                "wells": ["A1", "B1", "A2", "B2", "A3", "B3"],
            }
        ],
        "parameters": {
            "format": "irregular",
            "quirks": [],
            "isTiprack": is_tiprack,
            "isMagneticModuleCompatible": False,
            "loadName": load_name,
        },
        "namespace": namespace,
        "version": 1,
        "schemaVersion": 2,
        "cornerOffsetFromSlot": {"x": 0, "y": 0, "z": 0},
    }


class _FakeResponse:
    def __init__(self, payload, status_code=201):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _command_lifecycle_driver():
    driver = StubOT2HTTPDriver()
    driver._ot2_api_lock = threading.RLock()
    driver._ot2_command_fault = None
    driver._deck_stream_stop_event = threading.Event()
    driver.config.update({
        "ot2_command_timeout_seconds": 0.02,
        "ot2_command_poll_interval_seconds": 0.001,
        "ot2_stop_timeout_seconds": 0.01,
    })
    return driver


def test_atomic_command_submits_asynchronously_and_polls_to_success(monkeypatch):
    driver = _command_lifecycle_driver()
    posts = []
    gets = []

    def fake_post(**kwargs):
        posts.append(kwargs)
        return _FakeResponse({
            "data": {"id": "command-1", "status": "queued"}
        })

    def fake_get(**kwargs):
        gets.append(kwargs)
        return _FakeResponse({
            "data": {"id": "command-1", "status": "succeeded"}
        }, status_code=200)

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post
    )
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get", fake_get
    )

    result = OT2HTTPDriver._execute_atomic_command(
        driver, "dropTipInPlace", {"pipetteId": "pipette-1"}
    )

    assert result is True
    assert posts[0]["params"] == {"waitUntilComplete": False}
    assert posts[0]["timeout"] == (5.0, 15.0)
    assert gets[0]["url"].endswith("/runs/test-run/commands/command-1")
    assert driver._ot2_command_fault is None


def test_atomic_command_timeout_stops_run_and_raises(monkeypatch):
    driver = _command_lifecycle_driver()
    post_urls = []

    def fake_post(**kwargs):
        post_urls.append(kwargs["url"])
        if kwargs["url"].endswith("/commands"):
            return _FakeResponse({
                "data": {"id": "stuck-command", "status": "running"}
            })
        return _FakeResponse({"data": {"actionType": "stop"}})

    def fake_get(**kwargs):
        if "/commands/" in kwargs["url"]:
            return _FakeResponse({
                "data": {"id": "stuck-command", "status": "running"}
            }, status_code=200)
        return _FakeResponse({
            "data": {"id": "test-run", "status": "stopped"}
        }, status_code=200)

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post
    )
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get", fake_get
    )

    with pytest.raises(TimeoutError, match="stuck-command.*did not finish"):
        OT2HTTPDriver._execute_atomic_command(
            driver, "dropTipInPlace", {"pipetteId": "pipette-1"}
        )

    assert post_urls[-1].endswith("/runs/test-run/actions")
    assert driver._deck_stream_stop_event.is_set()
    assert driver.run_id is None
    assert driver._ot2_command_fault == {
        "run_id": "test-run",
        "command_id": "stuck-command",
        "command_type": "dropTipInPlace",
        "recovery": "run reached terminal state stopped",
    }


def test_atomic_command_timeout_returns_when_stop_remains_requested(monkeypatch):
    driver = _command_lifecycle_driver()

    def fake_post(**kwargs):
        if kwargs["url"].endswith("/commands"):
            return _FakeResponse({
                "data": {"id": "stuck-command", "status": "running"}
            })
        return _FakeResponse({"data": {"actionType": "stop"}})

    def fake_get(**kwargs):
        if "/commands/" in kwargs["url"]:
            return _FakeResponse({
                "data": {"id": "stuck-command", "status": "running"}
            }, status_code=200)
        return _FakeResponse({
            "data": {"id": "test-run", "status": "stop-requested"}
        }, status_code=200)

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post
    )
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get", fake_get
    )

    with pytest.raises(TimeoutError, match="stop requested but not confirmed"):
        OT2HTTPDriver._execute_atomic_command(
            driver, "dropTipInPlace", {"pipetteId": "pipette-1"}
        )

    assert driver.run_id == "test-run"
    with pytest.raises(RuntimeError, match="execution is quarantined"):
        OT2HTTPDriver._ensure_run_exists(driver)


def test_emergency_stop_stops_active_runs_and_clears_cached_run(monkeypatch):
    driver = StubOT2HTTPDriver()
    get_responses = iter([
        _FakeResponse({"data": [
            {"id": "active-run", "status": "running"},
            {"id": "old-run", "status": "stopped"},
        ]}, status_code=200),
        _FakeResponse({"data": {"id": "active-run", "status": "stopped"}}, status_code=200),
    ])
    posts = []
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get",
        lambda **kwargs: next(get_responses),
    )
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post",
        lambda **kwargs: posts.append(kwargs) or _FakeResponse({"data": {}}, status_code=201),
    )

    result = driver.emergency_stop(timeout=2)

    assert posts == [{
        "url": "http://ot2.test/runs/active-run/actions",
        "headers": {"Opentrons-Version": "2"},
        "json": {"data": {"actionType": "stop"}},
        "timeout": 2.0,
    }]
    assert result == {
        "stopped_run_ids": ["active-run"],
        "final_states": {"active-run": "stopped"},
        "active_run_ids": [],
    }
    assert driver.run_id is None


def test_emergency_stop_is_idempotent_when_all_runs_are_terminal(monkeypatch):
    driver = StubOT2HTTPDriver()
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get",
        lambda **kwargs: _FakeResponse({"data": [
            {"id": "stopped-run", "status": "stopped"},
            {"id": "failed-run", "status": "failed"},
        ]}, status_code=200),
    )

    def unexpected_post(**kwargs):
        raise AssertionError("No stop action should be sent for terminal runs")

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post", unexpected_post
    )

    result = driver.emergency_stop()

    assert result["stopped_run_ids"] == []
    assert result["active_run_ids"] == []
    assert driver.run_id is None


def test_emergency_stop_preserves_cached_run_when_stop_request_fails(monkeypatch):
    driver = StubOT2HTTPDriver()
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get",
        lambda **kwargs: _FakeResponse(
            {"data": [{"id": "active-run", "status": "running"}]},
            status_code=200,
        ),
    )
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post",
        lambda **kwargs: _FakeResponse({"errors": ["stop failed"]}, status_code=500),
    )

    with pytest.raises(RuntimeError, match="Failed to stop OT-2 run"):
        driver.emergency_stop(timeout=2)

    assert driver.run_id == "test-run"


def test_load_module_reports_an_actionable_attachment_error(monkeypatch):
    driver = StubOT2HTTPDriver()

    def fake_post(url, headers=None, params=None, json=None):
        assert json["data"]["commandType"] == "loadModule"
        return _FakeResponse(
            {
                "data": {
                    "status": "failed",
                    "error": {
                        "errorType": "ModuleNotAttachedError",
                        "errorCode": "4000",
                        "detail": "No available temperatureModuleV1 with any serial found.",
                    },
                }
            }
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        driver.load_module("temperatureModuleV1", "4")

    message = str(exc_info.value)
    assert "temperatureModuleV1" in message
    assert "deck slot '4'" in message
    assert "ModuleNotAttachedError (code 4000)" in message
    assert "No available temperatureModuleV1 with any serial found." in message
    assert "connected to the OT-2" in message
    assert "detected by the Opentrons hardware server" in message


def test_load_module_reuses_an_existing_matching_module_without_http_call(monkeypatch):
    driver = StubOT2HTTPDriver()
    driver.config["loaded_modules"]["4"] = ("module-4", "temperatureModuleV1")

    def unexpected_post(*args, **kwargs):
        raise AssertionError("An already-loaded matching module must not be loaded again")

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", unexpected_post)

    assert driver.load_module("temperatureModuleV1", 4) == "module-4"


def test_load_module_reports_a_conflicting_module_in_the_same_slot():
    driver = StubOT2HTTPDriver()
    driver.config["loaded_modules"]["4"] = ("module-4", "temperatureModuleV1")

    with pytest.raises(RuntimeError) as exc_info:
        driver.load_module("magneticModuleV2", "4")

    assert str(exc_info.value) == (
        "Cannot load module 'magneticModuleV2' in deck slot '4': slot already "
        "contains module 'temperatureModuleV1' with ID 'module-4'. Unload or "
        "reset the existing module before replacing it."
    )


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


def test_pipette_selection_uses_cached_loaded_metadata_without_refreshing():
    driver = _configured_driver()
    refresh_calls = []

    def unexpected_refresh():
        refresh_calls.append(True)
        raise AssertionError("pipette selection must not refresh robot metadata")

    driver._update_pipettes = unexpected_refresh

    assert driver.get_pipette(50)["mount"] == "left"
    assert driver._available_pipette_options()[0]["mount"] == "left"
    assert refresh_calls == []


def test_transfer_with_single_loaded_pipette_allows_rate_overrides():
    driver = _configured_driver()

    transfer_result = driver.transfer("1A1", "1A2", 50, aspirate_rate=111, dispense_rate=222)

    command_names = [name for name, _ in driver.executed_commands]
    assert "pickUpTip" in command_names
    assert "aspirate" in command_names
    assert "dispense" in command_names
    assert "moveToAddressableAreaForDropTip" in command_names
    assert "dropTipInPlace" in command_names
    assert driver.last_pipette == "left"
    assert transfer_result["requested_volume_ul"] == 50.0
    assert transfer_result["subtransfers_ul"] == [50.0]
    assert transfer_result["pipette_mount"] == "left"
    assert transfer_result["source"] == "1A1"
    assert transfer_result["dest"] == "1A2"


def test_transfer_below_configured_pipette_minimum_is_a_no_op():
    driver = _configured_driver()

    result = driver.transfer("1A1", "1A2", 1e-14)

    assert result == {
        "source": "1A1",
        "dest": "1A2",
        "requested_volume_ul": 1e-14,
        "minimum_configured_pipette_volume_ul": 20.0,
        "subtransfers_ul": [],
        "status": "skipped_below_minimum_pipette_volume",
    }
    assert driver.executed_commands == []
    assert driver.has_tip is False


def test_transfer_rounds_fractional_volume_to_an_integer_ul():
    driver = _configured_driver()

    result = driver.transfer("1A1", "1A2", 50.6)

    assert result["requested_volume_ul"] == 51
    aspirate = next(params for command, params in driver.executed_commands if command == "aspirate")
    dispense = next(params for command, params in driver.executed_commands if command == "dispense")
    assert aspirate["volume"] == 51
    assert dispense["volume"] == 51


def test_transfer_rejects_drop_tip_and_return_tip_together():
    driver = _configured_driver()

    with pytest.raises(ValueError, match="Only one of drop_tip and return_tip can be True"):
        driver.transfer("1A1", "1A2", 50, drop_tip=True, return_tip=True)


def test_transfer_with_tip_location_uses_requested_tip():
    driver = _configured_driver()
    # PersistentConfig JSON serialization restores tuple-like tip entries as
    # lists.  A requested tip must work with that persisted representation.
    driver.config["available_tips"]["left"] = [
        ["tiprack-left", "A1"],
        ["tiprack-left", "A2"],
    ]

    transfer_result = driver.transfer(
        "1A1",
        "1A2",
        50,
        drop_tip=False,
        tip_location="1A2",
    )

    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")
    assert pick_up["labwareId"] == "tiprack-left"
    assert pick_up["wellName"] == "A2"
    assert driver.current_tip["well_name"] == "A2"
    assert driver.config["available_tips"]["left"] == [["tiprack-left", "A1"]]
    assert transfer_result["requested_tip"]["location"] == "1A2"


def test_pickup_tip_uses_requested_tip_location_and_returns_metadata():
    driver = _configured_driver()

    pickup_result = driver.pickup_tip("1A2")

    move_to_well = next(params for command, params in driver.executed_commands if command == "moveToWell")
    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")
    assert move_to_well["labwareId"] == "tiprack-left"
    assert move_to_well["wellName"] == "A2"
    assert pick_up["labwareId"] == "tiprack-left"
    assert pick_up["wellName"] == "A2"
    assert pickup_result["mount"] == "left"
    assert pickup_result["pipette_id"] == "left-id"
    assert pickup_result["tip_location"] == "1A2"
    assert pickup_result["status"] == "picked_up"
    assert driver.current_tip["well_name"] == "A2"
    assert driver.config["available_tips"]["left"] == [("tiprack-left", "A1")]


def test_pickup_tip_with_local_offset_does_not_mutate_global_or_input_offsets():
    driver = _configured_driver()
    driver.config["tip_rack_offset"] = {
        "left": {"x": 0.0, "y": 0.0, "z": -2.0},
        "right": {"x": 1.0, "y": 2.0, "z": 3.0},
    }
    local_offset = {"x": 1.5, "y": -0.5, "z": -4.0}

    driver.pickup_tip("1A2", tip_rack_offset=local_offset)

    move_to_well = next(params for command, params in driver.executed_commands if command == "moveToWell")
    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")

    assert move_to_well["wellLocation"]["offset"] == {"x": 1.5, "y": -0.5, "z": 0}
    assert pick_up["wellLocation"]["offset"] == {"x": 1.5, "y": -0.5, "z": -4.0}
    assert local_offset == {"x": 1.5, "y": -0.5, "z": -4.0}
    assert driver.config["tip_rack_offset"] == {
        "left": {"x": 0.0, "y": 0.0, "z": -2.0},
        "right": {"x": 1.0, "y": 2.0, "z": 3.0},
    }


def test_pickup_tip_moves_above_tip_before_pickup():
    driver = _configured_driver()

    driver.pickup_tip("1A2", tip_rack_offset={"x": 1.0, "y": -1.0, "z": -3.0})

    move_index = next(i for i, (command, _) in enumerate(driver.executed_commands) if command == "moveToWell")
    pickup_index = next(i for i, (command, _) in enumerate(driver.executed_commands) if command == "pickUpTip")
    move_to_well = driver.executed_commands[move_index][1]
    pick_up = driver.executed_commands[pickup_index][1]

    assert move_index < pickup_index
    assert move_to_well["labwareId"] == "tiprack-left"
    assert move_to_well["wellName"] == "A2"
    assert move_to_well["wellLocation"]["origin"] == "top"
    assert move_to_well["wellLocation"]["offset"] == {"x": 1.0, "y": -1.0, "z": 0}
    assert pick_up["wellLocation"]["offset"] == {"x": 1.0, "y": -1.0, "z": -3.0}


def test_pickup_tip_rejects_when_different_tip_is_already_attached():
    driver = _configured_driver()
    driver.pickup_tip("1A1")

    with pytest.raises(RuntimeError, match="already attached"):
        driver.pickup_tip("1A2")


def test_return_tip_returns_attached_tip_to_origin():
    driver = _configured_driver()
    driver.pickup_tip("1A2")
    driver.executed_commands.clear()

    return_result = driver.return_tip("1A2")

    command_names = [name for name, _ in driver.executed_commands]
    assert "moveToWell" in command_names
    assert "dropTipInPlace" in command_names
    assert return_result["mount"] == "left"
    assert return_result["tip_location"] == "1A2"
    assert return_result["status"] == "returned"
    assert driver.has_tip is False
    assert driver.current_tip is None
    assert driver.config["available_tips"]["left"] == [
        ("tiprack-left", "A2"),
        ("tiprack-left", "A1"),
    ]


def test_return_tip_with_local_offset_does_not_mutate_global_or_input_offsets():
    driver = _configured_driver()
    driver.config["tip_rack_offset"] = {
        "left": {"x": 0.0, "y": 0.0, "z": -2.0},
        "right": {"x": 1.0, "y": 2.0, "z": 3.0},
    }
    local_offset = {"x": 1.5, "y": -0.5, "z": -4.0}
    driver.pickup_tip("1A2")
    driver.executed_commands.clear()

    driver.return_tip(
        "1A2",
        tip_rack_offset=local_offset,
        return_tip_z_offset=-1.0,
    )

    move_to_well = next(
        params
        for command, params in reversed(driver.executed_commands)
        if command == "moveToWell" and params.get("labwareId") == "tiprack-left"
    )
    drop_tip = next(params for command, params in driver.executed_commands if command == "dropTipInPlace")

    assert move_to_well["wellLocation"]["offset"] == {"x": 1.5, "y": -0.5, "z": -4.0}
    assert drop_tip["wellLocation"]["offset"] == {"x": 1.5, "y": -0.5, "z": -5.0}
    assert local_offset == {"x": 1.5, "y": -0.5, "z": -4.0}
    assert driver.config["tip_rack_offset"] == {
        "left": {"x": 0.0, "y": 0.0, "z": -2.0},
        "right": {"x": 1.0, "y": 2.0, "z": 3.0},
    }


def test_return_tip_without_attached_tip_is_noop():
    driver = _configured_driver()

    result = driver.return_tip("1A1")

    assert result == {"status": "no_tip_attached", "tip_location": "1A1"}
    assert driver.executed_commands == []


def test_transfer_with_tip_location_reuses_current_tip_when_already_attached():
    driver = _configured_driver()

    driver.transfer("1A1", "1A2", 50, drop_tip=False, tip_location="1A1")
    driver.executed_commands.clear()

    driver.transfer("1A1", "1A2", 50, drop_tip=False, tip_location="1A1")

    command_names = [name for name, _ in driver.executed_commands]
    assert "pickUpTip" not in command_names


def test_transfer_without_tip_location_skips_stock_reserved_tips():
    driver = _configured_driver()
    driver.config["reserved_stock_tips"] = ["1A1"]

    driver.transfer("1A1", "1A2", 50)

    move_to_well = next(params for command, params in driver.executed_commands if command == "moveToWell")
    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")
    assert move_to_well["labwareId"] == "tiprack-left"
    assert move_to_well["wellName"] == "A2"
    assert pick_up["wellName"] == "A2"
    assert driver.config["available_tips"]["left"] == [("tiprack-left", "A1")]


def test_transfer_moves_above_tip_before_pickup():
    driver = _configured_driver()
    driver.config["tip_rack_offset"] = {"x": 1.5, "y": -0.5, "z": -2.0}

    driver.transfer("1A1", "1A2", 50)

    move_index = next(i for i, (command, _) in enumerate(driver.executed_commands) if command == "moveToWell")
    pickup_index = next(i for i, (command, _) in enumerate(driver.executed_commands) if command == "pickUpTip")
    move_to_well = driver.executed_commands[move_index][1]
    pick_up = driver.executed_commands[pickup_index][1]

    assert move_index < pickup_index
    assert move_to_well["labwareId"] == "tiprack-left"
    assert move_to_well["wellName"] == "A1"
    assert move_to_well["wellLocation"]["offset"] == {"x": 1.5, "y": -0.5, "z": 0}
    assert pick_up["wellLocation"]["offset"] == {"x": 1.5, "y": -0.5, "z": -2.0}


def test_get_tip_status_reports_general_and_reserved_counts():
    driver = _configured_driver()
    driver.config["reserved_stock_tips"] = ["1A1"]

    status = driver.get_tip_status("left")

    assert status == "1/96 general tips available on left mount (1 reserved for stock pipetting)"


def test_transfer_without_tip_location_errors_when_only_reserved_stock_tips_remain():
    driver = _configured_driver()
    driver.config["reserved_stock_tips"] = ["1A1", "1A2"]

    with pytest.raises(RuntimeError, match="No unreserved tips available for left mount"):
        driver.transfer("1A1", "1A2", 50)


def test_transfer_with_unavailable_tip_location_raises():
    driver = _configured_driver()

    with pytest.raises(ValueError, match="Requested tip location 1A3 is not available"):
        driver.transfer("1A1", "1A2", 50, drop_tip=False, tip_location="1A3")


def test_transfer_return_tip_restores_tip_to_available_trace():
    driver = _configured_driver()

    driver.transfer("1A1", "1A2", 50, drop_tip=False, return_tip=True)

    command_names = [name for name, _ in driver.executed_commands]
    assert "moveToWell" in command_names
    assert "dropTipInPlace" in command_names
    assert driver.has_tip is False
    assert driver.current_tip is None
    assert driver.config["available_tips"]["left"] == [
        ("tiprack-left", "A1"),
        ("tiprack-left", "A2"),
    ]


def test_transfer_return_tip_uses_return_tip_z_offset():
    driver = _configured_driver()

    driver.transfer(
        "1A1",
        "1A2",
        50,
        drop_tip=False,
        return_tip=True,
        return_tip_z_offset=-7.0,
    )

    drop_tip_command = next(
        params for command, params in driver.executed_commands if command == "dropTipInPlace"
    )
    assert drop_tip_command["wellLocation"]["offset"]["z"] == -7.0


def test_split_transfer_drops_tip_without_force_new_tip():
    driver = _configured_driver()

    transfer_result = driver.transfer("1A1", "1A2", 350, drop_tip=True, force_new_tip=False)

    command_names = [name for name, _ in driver.executed_commands]
    assert command_names.count("pickUpTip") == 1
    assert command_names.count("moveToAddressableAreaForDropTip") == 1
    assert command_names.count("dropTipInPlace") == 1
    assert transfer_result["subtransfers_ul"] == [300.0, 50.0]
    assert driver.has_tip is False
    assert driver.current_tip is None


def test_split_transfer_logs_numbered_pipetting_plan(caplog):
    driver = _configured_driver()
    driver.app = SimpleNamespace(logger=logging.getLogger("test_ot2_transfer_plan"))

    with caplog.at_level(logging.INFO, logger="test_ot2_transfer_plan"):
        driver.transfer("1A1", "1A2", 350, drop_tip=True)

    assert [record.message for record in caplog.records] == [
        "Pipetting transfer plan 1/2: 1A1 -> 1A2 using p300_single (left), 300 uL",
        "Pipetting transfer plan 2/2: 1A1 -> 1A2 using p300_single (left), 50 uL",
    ]


@pytest.mark.parametrize(
    ("volume_ul", "expected_volumes"),
    [
        (320, [300.0, 20.0]),
        (330, [300.0, 20.0, 10.0]),
        (340, [300.0, 20.0, 20.0]),
        (350, [300.0, 20.0, 20.0, 10.0]),
    ],
)
def test_transfer_plan_uses_small_pipette_for_accurate_remainder(
    volume_ul, expected_volumes
):
    driver = _configured_driver()
    driver.hardware_pipettes["right"] = _pipette_info(
        "right", "right-id", min_volume=1, max_volume=20
    )
    driver.config["loaded_labware"]["2"] = (
        "tiprack-right",
        "opentrons_96_tiprack_20ul",
        {"definition": {"wells": {"A1": {}, "A2": {}}}},
    )
    driver.config["loaded_instruments"]["right"] = {
        "name": "p20_single",
        "pipette_id": "right-id",
        "tip_racks": ["tiprack-right"],
    }
    driver.config["available_tips"]["right"] = [("tiprack-right", "A1")]
    # Mirror the state change performed by load_instrument after loading the
    # second pipette into the active run.
    driver._update_pipettes()
    driver._update_pipette_ranges()

    transfer_result = driver.transfer("1A1", "1A2", volume_ul, drop_tip=True)

    assert transfer_result["subtransfers_ul"] == expected_volumes
    assert [step["mount"] for step in transfer_result["pipette_plan"]] == (
        ["left"] + ["right"] * (len(expected_volumes) - 1)
    )
    assert [step["volume_ul"] for step in transfer_result["pipette_plan"]] == expected_volumes
    aspirate_pipettes = [
        params["pipetteId"]
        for command, params in driver.executed_commands
        if command == "aspirate"
    ]
    assert aspirate_pipettes == ["left-id"] + ["right-id"] * (len(expected_volumes) - 1)


def test_mixed_pipette_transfer_uses_configured_tip_for_each_mount():
    driver = _configured_driver()
    driver.hardware_pipettes["right"] = _pipette_info(
        "right", "right-id", min_volume=1, max_volume=20
    )
    driver.config["loaded_labware"]["2"] = (
        "tiprack-right",
        "opentrons_96_tiprack_20ul",
        {"definition": {"wells": {"A1": {}, "A2": {}}}},
    )
    driver.config["loaded_instruments"]["right"] = {
        "name": "p20_single",
        "pipette_id": "right-id",
        "tip_racks": ["tiprack-right"],
    }
    driver.config["available_tips"]["right"] = [("tiprack-right", "A1")]
    driver._update_pipettes()
    driver._update_pipette_ranges()

    result = driver.transfer(
        "1A1",
        "1A2",
        350,
        drop_tip=False,
        return_tip=True,
        tip_locations=["1A1", "2A1"],
    )

    pickups = [params for command, params in driver.executed_commands if command == "pickUpTip"]
    assert [(params["pipetteMount"], params["labwareId"], params["wellName"]) for params in pickups] == [
        ("left", "tiprack-left", "A1"),
        ("right", "tiprack-right", "A1"),
    ]
    assert result["requested_tips"]["left"]["location"] == "1A1"
    assert result["requested_tips"]["right"]["location"] == "2A1"
    assert not any(
        command == "moveToAddressableAreaForDropTip"
        for command, _ in driver.executed_commands
    )
    assert ("tiprack-left", "A1") in driver.config["available_tips"]["left"]
    assert ("tiprack-right", "A1") in driver.config["available_tips"]["right"]


def test_split_transfer_force_new_tip_refreshes_tip_each_subtransfer():
    driver = _configured_driver()
    driver.config["available_tips"]["left"] = [
        ("tiprack-left", "A1"),
        ("tiprack-left", "A2"),
        ("tiprack-left", "A3"),
    ]

    transfer_result = driver.transfer("1A1", "1A2", 350, drop_tip=True, force_new_tip=True)

    command_names = [name for name, _ in driver.executed_commands]
    assert command_names.count("pickUpTip") == 2
    assert command_names.count("moveToAddressableAreaForDropTip") == 2
    assert command_names.count("dropTipInPlace") == 2
    assert transfer_result["subtransfers_ul"] == [300.0, 50.0]
    assert driver.has_tip is False
    assert driver.current_tip is None


def test_drop_tip_to_trash_targets_fixed_trash_before_drop():
    driver = _configured_driver()
    driver.has_tip = True
    driver.current_tip = {"mount": "left", "labware_id": "tiprack-left", "well_name": "A1"}

    driver._drop_tip_to_trash("left-id")

    assert driver.executed_commands[-2] == (
        "moveToAddressableAreaForDropTip",
        {
            "pipetteId": "left-id",
            "addressableAreaName": "fixedTrash",
            "alternateDropLocation": False,
        },
    )
    assert driver.executed_commands[-1] == (
        "dropTipInPlace",
        {"pipetteId": "left-id"},
    )
    assert driver.has_tip is False
    assert driver.current_tip is None


def test_drop_tip_to_trash_falls_back_when_fixed_trash_move_is_unavailable():
    driver = _configured_driver()
    driver.has_tip = True
    driver.current_tip = {"mount": "left", "labware_id": "tiprack-left", "well_name": "A1"}
    attempts = []

    def fake_execute(command, params, check_run_status=True):
        attempts.append((command, dict(params)))
        if command == "moveToAddressableAreaForDropTip":
            raise RuntimeError("unsupported command")
        if command == "dropTipInPlace":
            driver.has_tip = False
            driver.current_tip = None
        return {"commandType": command, "params": params}

    driver._execute_atomic_command = fake_execute

    driver._drop_tip_to_trash("left-id")

    assert attempts == [
        (
            "moveToAddressableAreaForDropTip",
            {
                "pipetteId": "left-id",
                "addressableAreaName": "fixedTrash",
                "alternateDropLocation": False,
            },
        ),
        ("dropTipInPlace", {"pipetteId": "left-id"}),
    ]
    assert driver.has_tip is False
    assert driver.current_tip is None


def test_transfer_tip_rack_offset_applies_to_pickup_and_return():
    driver = _configured_driver()
    offset = {"x": 1.5, "y": -0.5, "z": -2.0}

    transfer_result = driver.transfer(
        "1A1",
        "1A2",
        50,
        drop_tip=False,
        return_tip=True,
        tip_location="1A2",
        tip_rack_offset=offset,
    )

    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")
    move_to_well = next(
        params
        for command, params in reversed(driver.executed_commands)
        if command == "moveToWell" and params.get("labwareId") == "tiprack-left"
    )
    drop_tip = next(params for command, params in driver.executed_commands if command == "dropTipInPlace")

    assert pick_up["wellLocation"]["offset"] == offset
    assert move_to_well["wellLocation"]["offset"] == offset
    assert drop_tip["wellLocation"]["offset"] == offset
    assert transfer_result["options"]["tip_rack_offset"] == offset


def test_return_tip_z_offset_adds_to_local_return_z_without_mutating_tip_rack_offset():
    driver = _configured_driver()
    offset = {"x": 1.5, "y": -0.5, "z": -2.0}

    driver.transfer(
        "1A1",
        "1A2",
        50,
        drop_tip=False,
        return_tip=True,
        tip_location="1A2",
        tip_rack_offset=offset,
        return_tip_z_offset=-1.0,
    )

    move_to_well = next(
        params
        for command, params in reversed(driver.executed_commands)
        if command == "moveToWell" and params.get("labwareId") == "tiprack-left"
    )
    drop_tip = next(params for command, params in driver.executed_commands if command == "dropTipInPlace")
    expected_offset = {"x": 1.5, "y": -0.5, "z": -3.0}

    assert move_to_well["wellLocation"]["offset"] == offset
    assert drop_tip["wellLocation"]["offset"] == expected_offset
    assert offset == {"x": 1.5, "y": -0.5, "z": -2.0}
    assert driver.config["tip_rack_offset"] == {"x": 0, "y": 0, "z": 0}


def test_return_tip_z_offset_does_not_change_later_pickup_global_offset():
    driver = _configured_driver()
    driver.config["tip_rack_offset"] = {"x": 0.5, "y": 1.0, "z": -2.0}

    driver.transfer(
        "1A1",
        "1A2",
        50,
        drop_tip=False,
        return_tip=True,
        tip_location="1A2",
        return_tip_z_offset=-7.0,
    )
    driver.executed_commands.clear()

    driver.pickup_tip("1A1")

    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")

    assert driver.config["tip_rack_offset"] == {"x": 0.5, "y": 1.0, "z": -2.0}
    assert pick_up["wellLocation"]["offset"] == {"x": 0.5, "y": 1.0, "z": -2.0}


def test_return_tip_z_offset_does_not_mutate_mount_scoped_global_offsets():
    driver = _configured_driver()
    driver.config["tip_rack_offset"] = {
        "left": {"x": 0, "y": 0, "z": 0.0},
        "right": {"x": 1.0, "y": 2.0, "z": 3.0},
    }

    driver.transfer(
        "1A1",
        "1A2",
        50,
        drop_tip=False,
        return_tip=True,
        tip_location="1A2",
        return_tip_z_offset=-5.0,
    )
    move_to_well = next(
        params
        for command, params in reversed(driver.executed_commands)
        if command == "moveToWell" and params.get("labwareId") == "tiprack-left"
    )
    driver.executed_commands.clear()

    driver.pickup_tip("1A1")
    pick_up = next(params for command, params in driver.executed_commands if command == "pickUpTip")

    assert move_to_well["wellLocation"]["offset"] == {"x": 0, "y": 0, "z": 0.0}
    assert driver.config["tip_rack_offset"] == {
        "left": {"x": 0, "y": 0, "z": 0.0},
        "right": {"x": 1.0, "y": 2.0, "z": 3.0},
    }
    assert pick_up["wellLocation"]["offset"] == {"x": 0, "y": 0, "z": 0.0}


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


def test_send_labware_deduplicates_identical_content(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    requests_seen = []

    def fake_post(url, headers=None, params=None, json=None):
        requests_seen.append({"url": url, "json": json})
        return _FakeResponse(
            {"data": {"definitionUri": "custom_beta/nist_6_20ml_vials/1"}}
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    labware_def = _custom_labware_def(z_value=6.1)
    first = driver.send_labware(labware_def)
    second = driver.send_labware(_custom_labware_def(z_value=6.1))

    assert first["version"] == 1
    assert second["version"] == 1
    assert len(requests_seen) == 1
    assert requests_seen[0]["json"]["data"]["version"] == 1
    assert (tmp_path / "nist_6_20ml_vials.json").exists()
    assert not (tmp_path / "custom_beta_nist_6_20ml_vials.json").exists()


def test_send_labware_bumps_version_when_content_changes(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    uploaded_versions = []

    def fake_post(url, headers=None, params=None, json=None):
        version = json["data"]["version"]
        uploaded_versions.append(version)
        return _FakeResponse(
            {"data": {"definitionUri": f"custom_beta/nist_6_20ml_vials/{version}"}}
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    first = driver.send_labware(_custom_labware_def(z_value=6.1))
    second = driver.send_labware(_custom_labware_def(z_value=6.5))

    assert uploaded_versions == [1, 2]
    assert first["version"] == 1
    assert second["version"] == 2
    assert driver.sent_custom_labware["custom_beta/nist_6_20ml_vials"]["version"] == 2


def test_send_labware_does_not_reload_when_content_is_unchanged(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    original_def = _custom_labware_def(z_value=6.1)
    original_hash = driver._hash_labware_def(original_def)
    driver.sent_custom_labware["custom_beta/nist_6_20ml_vials"] = {
        "definition_uri": "custom_beta/nist_6_20ml_vials/1",
        "version": 1,
        "content_hash": original_hash,
    }
    driver.config["loaded_labware"]["2"] = (
        "labware-1",
        "nist_6_20ml_vials",
        {"definition": original_def},
    )
    requests_seen = []

    def fake_post(url, headers=None, params=None, json=None):
        requests_seen.append({"url": url, "json": json})
        return _FakeResponse({"data": {"result": {}}})

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    result = driver.send_labware(_custom_labware_def(z_value=6.1))

    assert result["version"] == 1
    assert requests_seen == []
    assert driver.config["loaded_labware"]["2"][0] == "labware-1"
    assert driver.config["loaded_labware"]["2"][2]["definition"]["wells"]["A1"]["z"] == 6.1


def test_send_labware_reloads_matching_loaded_labware(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    original_def = _custom_labware_def(z_value=6.1)
    driver.sent_custom_labware["custom_beta/nist_6_20ml_vials"] = {
        "definition_uri": "custom_beta/nist_6_20ml_vials/1",
        "version": 1,
        "content_hash": driver._hash_labware_def(original_def),
    }
    driver.config["loaded_labware"]["2"] = (
        "labware-1",
        "nist_6_20ml_vials",
        {"definition": original_def},
    )
    posted_command_types = []

    def fake_post(url, headers=None, params=None, json=None):
        if url.endswith("/labware_definitions"):
            return _FakeResponse(
                {"data": {"definitionUri": "custom_beta/nist_6_20ml_vials/2"}}
            )

        posted_command_types.append(json["data"]["commandType"])
        if json["data"]["commandType"] == "moveLabware":
            return _FakeResponse({"data": {"result": {}}})
        if json["data"]["commandType"] == "loadLabware":
            assert json["data"]["params"]["version"] == 2
            updated_def = _custom_labware_def(z_value=6.5)
            updated_def["version"] = 2
            return _FakeResponse(
                {
                    "data": {
                        "result": {
                            "labwareId": "labware-2",
                            "definition": updated_def,
                        }
                    }
                }
            )
        raise AssertionError(f"Unexpected command payload: {json}")

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    result = driver.send_labware(_custom_labware_def(z_value=6.5))

    assert result["version"] == 2
    assert posted_command_types == ["moveLabware", "loadLabware"]
    assert driver.config["loaded_labware"]["2"][0] == "labware-2"
    assert driver.config["loaded_labware"]["2"][2]["definition"]["version"] == 2
    assert driver.config["loaded_labware"]["2"][2]["definition"]["wells"]["A1"]["z"] == 6.5


def test_send_labware_reloads_tiprack_and_affected_pipette(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    original_tiprack = _custom_labware_def(
        z_value=6.1,
        load_name="nist_300ul_tiprack",
        is_tiprack=True,
        display_category="tipRack",
    )
    updated_tiprack = _custom_labware_def(
        z_value=6.5,
        load_name="nist_300ul_tiprack",
        is_tiprack=True,
        display_category="tipRack",
    )
    driver.sent_custom_labware["custom_beta/nist_300ul_tiprack"] = {
        "definition_uri": "custom_beta/nist_300ul_tiprack/1",
        "version": 1,
        "content_hash": driver._hash_labware_def(original_tiprack),
    }
    driver.config["loaded_labware"]["1"] = (
        "tiprack-old",
        "nist_300ul_tiprack",
        {"definition": original_tiprack},
    )
    driver.config["loaded_instruments"]["left"] = {
        "name": "p300_single",
        "pipette_id": "pipette-old",
        "tip_racks": ["tiprack-old"],
    }
    driver.config["available_tips"]["left"] = [
        ("tiprack-old", "A1"),
        ("tiprack-old", "A2"),
    ]
    driver.hardware_pipettes = {
        "left": _pipette_info("left", None, min_volume=20, max_volume=300),
    }
    driver.has_tip = True
    command_types = []

    def fake_post(url, headers=None, params=None, json=None):
        if url.endswith("/labware_definitions"):
            return _FakeResponse(
                {"data": {"definitionUri": "custom_beta/nist_300ul_tiprack/2"}}
            )

        command_type = json["data"]["commandType"]
        command_types.append(command_type)
        if command_type == "moveLabware":
            return _FakeResponse({"data": {"result": {}}})
        if command_type == "loadLabware":
            assert json["data"]["params"]["version"] == 2
            return _FakeResponse(
                {
                    "data": {
                        "result": {
                            "labwareId": "tiprack-new",
                            "definition": {**updated_tiprack, "version": 2},
                        }
                    }
                }
            )
        if command_type == "loadPipette":
            assert json["data"]["params"]["tip_racks"] == ["tiprack-new"]
            return _FakeResponse(
                {"data": {"result": {"pipetteId": "pipette-new"}}}
            )
        raise AssertionError(f"Unexpected command payload: {json}")

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    result = driver.send_labware(updated_tiprack)

    assert result["version"] == 2
    assert command_types == ["moveLabware", "loadLabware", "loadPipette"]
    assert driver.config["loaded_labware"]["1"][0] == "tiprack-new"
    assert driver.config["loaded_instruments"]["left"]["pipette_id"] == "pipette-new"
    assert driver.config["loaded_instruments"]["left"]["tip_racks"] == ["tiprack-new"]
    assert driver.config["available_tips"]["left"] == [
        ("tiprack-new", "A1"),
        ("tiprack-new", "A2"),
    ]
    assert driver.has_tip is False
    assert driver.last_pipette is None


def test_load_labware_uses_resolved_custom_version(monkeypatch, tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path
    upload_versions = []
    load_versions = []

    def fake_post(url, headers=None, params=None, json=None):
        if url.endswith("/labware_definitions"):
            version = json["data"]["version"]
            upload_versions.append(version)
            return _FakeResponse(
                {"data": {"definitionUri": f"custom_beta/nist_6_20ml_vials/{version}"}}
            )

        command_type = json["data"]["commandType"]
        if command_type == "moveLabware":
            return _FakeResponse({"data": {"result": {}}})

        params_payload = json["data"]["params"]
        load_versions.append(params_payload["version"])
        version = params_payload["version"]
        definition = _custom_labware_def(z_value=6.5 if version == 2 else 6.1)
        definition["version"] = version
        return _FakeResponse(
            {
                "data": {
                    "result": {
                        "labwareId": f"labware-{version}",
                        "definition": definition,
                    }
                }
            }
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    driver.load_labware("custom_beta/nist_6_20ml_vials", "2", labware_json=_custom_labware_def(z_value=6.1))
    driver.load_labware("custom_beta/nist_6_20ml_vials", "2", labware_json=_custom_labware_def(z_value=6.5))

    assert upload_versions == [1, 2]
    assert load_versions == [1, 2]
    assert driver.config["loaded_labware"]["2"][2]["definition"]["version"] == 2
    assert driver.config["loaded_labware"]["2"][2]["definition"]["wells"]["A1"]["z"] == 6.5


def test_load_custom_labware_defs_rejects_duplicate_keys(tmp_path):
    driver = StubOT2HTTPDriver()
    driver.custom_labware_dir = tmp_path

    first = _custom_labware_def(z_value=6.1)
    second = _custom_labware_def(z_value=6.5)

    with open(tmp_path / "nist_6_20ml_vials.json", "w") as f:
        json.dump(first, f)
    with open(tmp_path / "custom_beta_nist_6_20ml_vials.json", "w") as f:
        json.dump(second, f)

    with pytest.raises(ValueError, match="Duplicate custom labware definitions"):
        driver._load_custom_labware_defs()


def test_driver_bootstraps_user_labware_dir_on_first_init(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    seed_dir = tmp_path / "seed_labware"
    seed_dir.mkdir()
    seed_file = seed_dir / "seed_plate.json"
    with open(seed_file, "w") as f:
        json.dump(_custom_labware_def(load_name="seed_plate"), f)

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(
        OT2HTTPDriver,
        "_get_seed_custom_labware_dir",
        lambda self: seed_dir,
    )

    driver = OT2HTTPDriver()

    expected_dir = home_dir / ".afl" / "opentrons_labware"
    assert driver.custom_labware_dir == expected_dir
    assert expected_dir.exists()
    assert (expected_dir / "seed_plate.json").exists()
    assert driver.custom_labware_files["custom_beta/seed_plate"] == expected_dir / "seed_plate.json"


def test_driver_does_not_reseed_existing_user_labware_dir(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    expected_dir = home_dir / ".afl" / "opentrons_labware"
    expected_dir.mkdir(parents=True)

    existing_def = _custom_labware_def(z_value=9.9)
    with open(expected_dir / "nist_6_20ml_vials.json", "w") as f:
        json.dump(existing_def, f)

    seed_dir = tmp_path / "seed_labware"
    seed_dir.mkdir()
    with open(seed_dir / "nist_6_20ml_vials.json", "w") as f:
        json.dump(_custom_labware_def(z_value=6.1), f)
    with open(seed_dir / "seed_only.json", "w") as f:
        json.dump(_custom_labware_def(load_name="seed_only"), f)

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(
        OT2HTTPDriver,
        "_get_seed_custom_labware_dir",
        lambda self: seed_dir,
    )

    driver = OT2HTTPDriver()

    with open(expected_dir / "nist_6_20ml_vials.json", "r") as f:
        persisted = json.load(f)

    assert driver.custom_labware_dir == expected_dir
    assert persisted["wells"]["A1"]["z"] == 9.9
    assert not (expected_dir / "seed_only.json").exists()


def test_get_available_wells_returns_sorted_unoccupied_locations():
    driver = StubOT2HTTPDriver()
    driver.config["loaded_labware"]["5"] = (
        "plate-5",
        "custom_plate",
        {"definition": {"wells": {"B2": {}, "A10": {}, "A2": {}, "A1": {}, "B1": {}}}},
    )
    driver.config["occupied_sample_locations"] = ["5A2", "5b1"]

    result = driver.get_available_wells(5)

    assert result == ["5A1", "5A10", "5B2"]


def test_get_available_wells_raises_for_missing_slot():
    driver = StubOT2HTTPDriver()

    with pytest.raises(ValueError, match="No labware loaded in slot 9"):
        driver.get_available_wells("9")


def test_send_labware_persists_to_user_labware_dir(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    seed_dir = tmp_path / "seed_labware"
    seed_dir.mkdir()

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(
        OT2HTTPDriver,
        "_get_seed_custom_labware_dir",
        lambda self: seed_dir,
    )

    driver = OT2HTTPDriver()
    driver._ensure_run_exists = lambda check_run_status=True: "test-run"

    def fake_post(url, headers=None, params=None, json=None):
        return _FakeResponse(
            {"data": {"definitionUri": "custom_beta/nist_6_20ml_vials/1"}}
        )

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)

    driver.send_labware(_custom_labware_def(z_value=6.5))

    expected_file = home_dir / ".afl" / "opentrons_labware" / "nist_6_20ml_vials.json"
    with open(expected_file, "r") as f:
        persisted = json.load(f)

    assert expected_file.exists()
    assert persisted["wells"]["A1"]["z"] == 6.5


class _DeckPictureResponse:
    content = b"fake-jpeg"

    def raise_for_status(self):
        return None


class _DeckPictureErrorResponse:
    status_code = 500
    text = '{"message":"camera service unavailable"}'

    def raise_for_status(self):
        raise requests.exceptions.HTTPError("500 Server Error")


class _DeckLightResponse:
    def __init__(self, on):
        self.on = on

    def raise_for_status(self):
        return None

    def json(self):
        return {"on": self.on}


class _DeckStreamWriter:
    def __init__(self, path, *args):
        self.path = Path(path)
        self.frames = []

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.path.write_bytes(b"video-" + str(len(self.frames)).encode())


class _DeckStreamCV2:
    IMREAD_COLOR = 1

    def __init__(self):
        self.writers = []

    def imdecode(self, encoded, mode):
        assert encoded.tobytes() == b"fake-jpeg"
        return np.zeros((2, 3, 3), dtype=np.uint8)

    def resize(self, frame, dimensions):
        return np.zeros((dimensions[1], dimensions[0], 3), dtype=np.uint8)

    def VideoWriter_fourcc(self, *codec):
        assert codec == ("m", "p", "4", "v")
        return 0

    def VideoWriter(self, *args):
        writer = _DeckStreamWriter(*args)
        self.writers.append(writer)
        return writer


def _deck_stream_driver(tmp_path):
    driver = StubOT2HTTPDriver()
    driver.path = tmp_path
    driver.config.update({
        "deck_stream_video_fps": 1,
        "enable_deck_stream": False,
    })
    driver._deck_stream_thread = None
    driver._deck_stream_stop_event = None
    driver._deck_stream_lock = threading.Lock()
    driver._deck_stream_state = {
        "running": False,
        "current_window_started_at": None,
        "last_completed_at": None,
        "last_video_path": None,
        "last_frame_count": 0,
        "last_error": None,
        "stopped_for_run_status": None,
        "task_name": None,
        "capture_started_at": None,
        "output_path": None,
    }
    return driver


def test_task_video_settings_use_fps(tmp_path):
    driver = _deck_stream_driver(tmp_path)

    settings = driver._task_video_settings()

    assert settings["directory"] == tmp_path / "ot2_deck_stream"
    assert settings["capture_period_seconds"] == 1
    driver.config["deck_stream_video_fps"] = 0
    with pytest.raises(ValueError, match="FPS must be positive"):
        driver._task_video_settings()


def test_standalone_deck_stream_tasks_are_not_exposed(tmp_path):
    driver = _deck_stream_driver(tmp_path)

    assert not hasattr(driver, "get_deck_stream")
    assert not hasattr(driver, "stop_deck_stream")


def test_task_video_can_use_a_fixed_overwrite_path(monkeypatch, tmp_path):
    driver = _deck_stream_driver(tmp_path)
    driver.config["enable_deck_stream"] = True
    logged = []
    monkeypatch.setattr(driver, "log_info", logged.append)
    monkeypatch.setattr(driver, "_ensure_deck_lights_on", lambda: False)

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            return None

        def is_alive(self):
            return False

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.threading.Thread", FakeThread
    )

    assert driver._start_task_video("prepare", output_filename="prepare.mp4") is True
    assert driver._deck_stream_state["task_name"] == "prepare"
    expected_directory = tmp_path / "ot2_deck_stream"
    assert expected_directory.is_dir()
    assert len(logged) == 1
    assert logged[0].startswith("Task video capture started at ")
    assert "for task 'prepare'" in logged[0]
    assert logged[0].endswith(f"output={expected_directory}/prepare.mp4")
    assert driver._deck_stream_state["capture_started_at"] is not None
    assert driver._deck_stream_state["output_path"] == str(
        expected_directory / "prepare.mp4"
    )


def test_finish_task_video_logs_stop_and_save_initiation(monkeypatch, tmp_path):
    driver = _deck_stream_driver(tmp_path)
    logged = []
    monkeypatch.setattr(driver, "log_info", logged.append)

    class FinishedThread:
        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False

    driver._deck_stream_stop_event = threading.Event()
    driver._deck_stream_thread = FinishedThread()
    driver._deck_stream_state.update({
        "running": True,
        "task_name": "prepare",
        "output_path": str(tmp_path / "ot2_deck_stream" / "prepare.mp4"),
    })

    driver._finish_task_video()

    assert driver._deck_stream_stop_event is None
    assert len(logged) == 1
    assert logged[0].startswith("Task video stop/save initiated at ")
    assert "for task 'prepare'" in logged[0]
    assert logged[0].endswith(
        f"output={tmp_path / 'ot2_deck_stream' / 'prepare.mp4'}"
    )


def test_deck_stream_turns_lights_on_only_when_needed(monkeypatch, tmp_path):
    driver = _deck_stream_driver(tmp_path)
    requests_sent = []

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get",
        lambda **kwargs: _DeckLightResponse(on=False),
    )
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post",
        lambda **kwargs: requests_sent.append(kwargs) or _DeckLightResponse(on=True),
    )

    assert driver._ensure_deck_lights_on() is True
    assert requests_sent == [{
        "url": "http://ot2.test/robot/lights",
        "headers": {"Opentrons-Version": "2"},
        "json": {"on": True},
        "timeout": 15,
    }]

    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.get",
        lambda **kwargs: _DeckLightResponse(on=True),
    )
    assert driver._ensure_deck_lights_on() is False
    assert len(requests_sent) == 1


def test_enabled_deck_stream_does_not_start_worker_during_initialization(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(OT2HTTPDriver, "_initialize_robot", lambda self: None)
    monkeypatch.setattr(OT2HTTPDriver, "_get_seed_custom_labware_dir", lambda self: None)
    driver = OT2HTTPDriver({"enable_deck_stream": True})

    assert driver._deck_stream_thread is None


def test_deck_stream_window_fetches_camera_picture_and_replaces_video(monkeypatch, tmp_path):
    driver = _deck_stream_driver(tmp_path)
    cv2_module = _DeckStreamCV2()
    captured_request = {}
    logged = []

    def fake_post(**kwargs):
        captured_request.update(kwargs)
        return _DeckPictureResponse()

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", fake_post)
    monkeypatch.setattr(driver, "_deck_stream_cv2", lambda: cv2_module)
    monkeypatch.setattr(driver, "log_info", logged.append)
    output_dir = tmp_path / "ot2_deck_stream"
    output_dir.mkdir()
    output_path = output_dir / "deck_stream.mp4"
    output_path.write_bytes(b"old-video")

    result = driver._record_deck_stream_window({
        "directory": output_dir,
        "capture_period_seconds": 0.001,
        "duration_seconds": 0.002,
        "video_fps": 1,
        "request_timeout": 15,
    })

    assert captured_request == {
        "url": "http://ot2.test/camera/picture",
        "headers": {"Opentrons-Version": "2"},
        "timeout": 15,
    }
    assert result["path"] == str(output_path)
    assert output_path.read_bytes().startswith(b"video-")
    assert driver._deck_stream_state["last_video_path"] == str(output_path)
    assert driver._deck_stream_state["last_frame_count"] >= 1
    assert len(logged) == 1
    assert logged[0].startswith("Task video saved at ")
    assert f"output={output_path}" in logged[0]
    assert f"frames={result['frame_count']}" in logged[0]


def test_deck_stream_includes_ot2_camera_error_details(monkeypatch, tmp_path):
    driver = _deck_stream_driver(tmp_path)
    monkeypatch.setattr(
        "AFL.automation.prepare.OT2HTTPDriver.requests.post",
        lambda **kwargs: _DeckPictureErrorResponse(),
    )

    with pytest.raises(RuntimeError, match="camera service unavailable"):
        driver._capture_deck_picture(_DeckStreamCV2(), timeout=15)




def test_deck_stream_empty_window_preserves_previous_video(monkeypatch, tmp_path):
    driver = _deck_stream_driver(tmp_path)
    output_dir = tmp_path / "ot2_deck_stream"
    output_dir.mkdir()
    output_path = output_dir / "deck_stream.mp4"
    output_path.write_bytes(b"old-video")
    monkeypatch.setattr(driver, "_deck_stream_cv2", lambda: _DeckStreamCV2())

    def failing_post(**kwargs):
        raise requests.exceptions.ConnectionError("camera unavailable")

    monkeypatch.setattr("AFL.automation.prepare.OT2HTTPDriver.requests.post", failing_post)
    with pytest.raises(RuntimeError, match="camera unavailable"):
        driver._record_deck_stream_window({
            "directory": output_dir,
            "capture_period_seconds": 0.001,
            "duration_seconds": 0.002,
            "video_fps": 1,
            "request_timeout": 15,
        })

    assert output_path.read_bytes() == b"old-video"
    assert "camera unavailable" in driver._deck_stream_state["last_error"]
