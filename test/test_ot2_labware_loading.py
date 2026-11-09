from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from AFL.automation.manipulate.ufactory_xarm.labware import Vial
from AFL.automation.manipulate.ufactory_xarm import ufactory
from AFL.automation.manipulate.ufactory_xarm.stations import OT2
from AFL.automation.manipulate.ufactory_xarm.ufactory import Attachment, xArmManipulator
from AFL.automation.manipulate.ufactory_xarm.xArmHTTPDriver import xArmHTTPDriver


@pytest.fixture
def driver(tmp_path, monkeypatch):
    monkeypatch.setenv("AFL_HOME", str(tmp_path / "afl"))
    monkeypatch.setenv("AFL_FRESH_DRIVER_CONFIG", "1")
    monkeypatch.setattr(xArmManipulator, "connect", lambda self: self)
    workcell = Path(ufactory.__file__).with_name("configs") / "workcell.yaml"
    return xArmHTTPDriver(
        stations=[OT2()],
        overrides={"simulation": True, "workcell_config": str(workcell)},
    )


@pytest.fixture
def definition():
    return {"parameters": {"loadName": "custom_rack"}, "wells": {"A1": {"x": 10}}}


@pytest.fixture
def rack_loader(driver, monkeypatch):
    rack = Mock()
    rack.wells_by_name.return_value = {"A1": Mock(), "B1": Mock()}
    protocol = Mock()
    protocol.load_labware_from_definition.return_value = rack
    monkeypatch.setattr(driver.stations["OT2"], "_simulator_protocol", lambda: protocol)
    return protocol.load_labware_from_definition


def load_rack(driver, definition, **options):
    return driver.execute(
        task_name="station_operation", station="OT2", operation="load_labware",
        definition=definition, slot=options.pop("slot", "2"), label=options.pop("label", "rack"),
        **options,
    )


def test_loading_is_exposed_on_the_station_only(driver):
    assert "load_labware" in driver.list_stations()["OT2"]["operations"]
    assert "load_custom_labware" not in driver.list_stations()["OT2"]["operations"]
    assert not hasattr(driver, "load_ot2_labware")


def test_afl_dispatch_registers_wells_and_reuses_identical_rack(driver, definition, rack_loader):
    expected = {"name": "rack", "slot": "2", "wells": ["A1", "B1"]}
    assert load_rack(driver, definition) == expected
    assert load_rack(driver, deepcopy(definition), slot=2) == expected
    rack_loader.assert_called_once_with(definition, location="2", label="rack")
    station = driver.stations["OT2"]
    rack = station.loaded_labware["rack"]
    for name, well in rack.wells_by_name().items():
        assert station.resolve_address(f"2{name}") is well


@pytest.mark.parametrize("conflict", ["definition", "slot", "label"])
def test_existing_rack_cannot_be_replaced_or_overlapped(driver, definition, rack_loader, conflict):
    load_rack(driver, definition)
    changed = deepcopy(definition)
    options = {}
    if conflict == "definition":
        changed["wells"]["A1"]["x"] += 1
    elif conflict == "slot":
        options["slot"] = "4"
    else:
        options["label"] = "other"
    with pytest.raises(ValueError, match="already registered|occupied"):
        load_rack(driver, changed, **options)
    assert rack_loader.call_count == 1
    assert list(driver.stations["OT2"].loaded_labware) == ["rack"]


def test_module_slot_is_rejected_before_simulator_loading(driver, definition, rack_loader):
    station = driver.stations["OT2"]
    module = Mock()
    station.loaded_modules["temperature"] = module
    station._module_slots[id(module)] = "2"
    with pytest.raises(ValueError, match="occupied"):
        load_rack(driver, definition)
    rack_loader.assert_not_called()


def test_held_vial_is_rejected_before_loading(driver, definition, rack_loader):
    driver.arm._attachment = Attachment(Vial("held"), (0.,) * 6)
    with pytest.raises(ValueError, match="before picking up"):
        load_rack(driver, definition)
    rack_loader.assert_not_called()


def test_paused_handoff_is_rejected_before_loading(driver, definition, rack_loader):
    station = driver.stations["OT2"]
    driver.arm._set_station_context(
        station, "placement", Vial("paused"), "2A1", (0.,) * 6,
        ((0.,) * 7,), "vertical", (), release_allowed=True,
    )
    with pytest.raises(RuntimeError, match="paused"):
        load_rack(driver, definition)
    rack_loader.assert_not_called()


@pytest.mark.parametrize("slot", [True, 0, 13, "2.0"])
def test_invalid_slots_do_not_reach_simulator(driver, definition, rack_loader, slot):
    with pytest.raises(ValueError, match="deck slot"):
        load_rack(driver, definition, slot=slot)
    rack_loader.assert_not_called()


def test_simulator_failure_leaves_registry_unchanged(driver, definition, rack_loader):
    rack_loader.side_effect = RuntimeError("invalid schema")
    with pytest.raises(RuntimeError, match="invalid schema"):
        load_rack(driver, definition)
    station = driver.stations["OT2"]
    assert station.loaded_labware == {}
    assert station._registered_wells == {}
    assert station._custom_labware_definitions == {}


def test_definition_snapshot_is_independent_of_caller_mutation(driver, definition, rack_loader):
    load_rack(driver, definition)
    definition["wells"]["A1"]["x"] += 1
    assert driver.stations["OT2"]._custom_labware_definitions["rack"]["wells"]["A1"]["x"] == 10


def test_named_loading_uses_the_same_station_operation(driver, rack_loader):
    station = driver.stations["OT2"]
    protocol = station._simulator_protocol()
    protocol.load_labware.return_value = rack_loader.return_value
    result = driver.execute(
        task_name="station_operation", station="OT2", operation="load_labware",
        load_name="standard_rack", slot="2", label="rack", namespace="opentrons", version=1,
    )
    assert result == {"name": "rack", "slot": "2", "wells": ["A1", "B1"]}
    protocol.load_labware.assert_called_once_with(
        "standard_rack", location="2", namespace="opentrons", version=1,
    )
    rack_loader.assert_not_called()


@pytest.mark.parametrize("positional", [True, False])
def test_direct_native_loading_still_returns_native_labware(driver, rack_loader, positional):
    station = driver.stations["OT2"]
    protocol = station._simulator_protocol()
    protocol.load_labware.return_value = rack_loader.return_value
    if positional:
        result = station.load_labware("standard_rack", "2", label="rack")
    else:
        result = station.load_labware(load_name="standard_rack", slot="2", label="rack")
    assert result is rack_loader.return_value


def test_direct_custom_loading_returns_native_labware(driver, definition, rack_loader):
    result = driver.stations["OT2"].load_labware(definition=definition, slot="2", label="rack")
    assert result is rack_loader.return_value


def test_queued_custom_loading_resolves_a_registered_module_name(driver, definition, rack_loader):
    station = driver.stations["OT2"]
    module = Mock()
    module.load_labware_from_definition.return_value = rack_loader.return_value
    station.loaded_modules["temperature"] = module
    station._module_slots[id(module)] = "3"
    result = load_rack(driver, definition, slot="temperature")
    assert result == {"name": "rack", "slot": "3", "wells": ["A1", "B1"]}
    module.load_labware_from_definition.assert_called_once_with(definition, label="rack")
    rack_loader.assert_not_called()


def test_configured_module_and_rack_still_load_during_construction(monkeypatch):
    protocol = Mock()
    module = protocol.load_module.return_value
    rack = module.load_labware.return_value
    rack.wells_by_name.return_value = {"A1": Mock()}
    monkeypatch.setattr(OT2, "_simulator_protocol", lambda self: protocol)
    station = OT2(
        module_definitions={"temperature": {"model": "temperatureModuleV1", "slot": "3"}},
        labware_definitions={"rack": {"load_name": "standard_rack", "location": "temperature"}},
    )
    assert station.loaded_labware["rack"] is rack
    module.load_labware.assert_called_once_with("standard_rack")


@pytest.mark.parametrize("source", ["definition", "definition_path"])
def test_custom_rack_can_be_declared_in_startup_config(tmp_path, monkeypatch, definition, source):
    protocol = Mock()
    rack = protocol.load_labware_from_definition.return_value
    rack.wells_by_name.return_value = {"A1": Mock(), "B1": Mock()}
    monkeypatch.setattr(OT2, "_simulator_protocol", lambda self: protocol)
    if source == "definition_path":
        path = tmp_path / "rack.json"
        path.write_text(json.dumps(definition))
        value = str(path)
    else:
        value = definition
    station = OT2(labware_definitions={"rack": {source: value, "location": "2"}})
    protocol.load_labware_from_definition.assert_called_once_with(definition, location="2", label="rack")
    assert station.loaded_labware["rack"] is rack
    assert station.resolve_address("2A1") is rack.wells_by_name()["A1"]


@pytest.mark.parametrize("sources", [{}, {"load_name": "rack", "definition": {}}, {"definition": {}, "definition_path": "rack.json"}])
def test_startup_requires_one_labware_definition_source(sources):
    with pytest.raises(ValueError, match="exactly one"):
        OT2(labware_definitions={"rack": {"location": "2", **sources}})


@pytest.mark.parametrize("contents", [None, "{malformed json"])
def test_unreadable_custom_definition_reports_its_path(tmp_path, contents):
    path = tmp_path / "rack.json"
    if contents is not None:
        path.write_text(contents)
    with pytest.raises(ValueError, match="could not read OT-2 labware definition"):
        OT2(labware_definitions={"rack": {"definition_path": str(path), "location": "2"}})
