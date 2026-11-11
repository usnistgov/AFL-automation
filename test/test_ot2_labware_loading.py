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
    assert "load_module" in driver.list_stations()["OT2"]["operations"]
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


@pytest.mark.parametrize("clearance", [True, False, "5", -1, float("nan"), float("inf")])
def test_invalid_clearance_is_rejected_before_native_loading(driver, definition, rack_loader, clearance):
    with pytest.raises(ValueError, match="deck_clearance_mm"):
        load_rack(driver, definition, deck_clearance_mm=clearance)
    rack_loader.assert_not_called()
    station = driver.stations["OT2"]
    assert station._slot_deck_clearance_m == {}
    assert station.loaded_labware == {}


@pytest.mark.parametrize("clearance", [0, 7.5, 30])
def test_clearance_is_stored_in_metres_for_the_physical_slot(driver, definition, rack_loader, clearance):
    result = load_rack(driver, definition, deck_clearance_mm=clearance)
    assert result["deck_clearance_mm"] == clearance
    assert driver.stations["OT2"]._slot_deck_clearance_m == {"2": clearance / 1000.}
    rack_loader.assert_called_once_with(definition, location="2", label="rack")


def test_identical_custom_reload_updates_clearance_and_omission_preserves_it(driver, definition, rack_loader):
    load_rack(driver, definition, deck_clearance_mm=5)
    updated = load_rack(driver, deepcopy(definition), deck_clearance_mm=12)
    assert updated["deck_clearance_mm"] == 12
    assert load_rack(driver, definition) == updated
    assert load_rack(driver, definition, deck_clearance_mm=None) == updated
    assert driver.stations["OT2"]._slot_deck_clearance_m == {"2": .012}
    assert rack_loader.call_count == 1


def test_conflicting_reload_cannot_change_clearance(driver, definition, rack_loader):
    load_rack(driver, definition, deck_clearance_mm=5)
    changed = deepcopy(definition)
    changed["wells"]["A1"]["x"] += 1
    with pytest.raises(ValueError, match="already registered"):
        load_rack(driver, changed, deck_clearance_mm=30)
    assert driver.stations["OT2"]._slot_deck_clearance_m == {"2": .005}
    assert rack_loader.call_count == 1


def test_native_loading_failure_cannot_set_clearance(driver, definition, rack_loader):
    rack_loader.side_effect = RuntimeError("invalid schema")
    with pytest.raises(RuntimeError, match="invalid schema"):
        load_rack(driver, definition, deck_clearance_mm=5)
    assert driver.stations["OT2"]._slot_deck_clearance_m == {}


def test_named_labware_accepts_clearance_without_forwarding_it_to_opentrons(driver, rack_loader):
    station = driver.stations["OT2"]
    protocol = station._simulator_protocol()
    protocol.load_labware.return_value = rack_loader.return_value
    station.load_labware("standard_rack", "1", deck_clearance_mm=8)
    assert station._slot_deck_clearance_m == {"1": .008}
    protocol.load_labware.assert_called_once_with("standard_rack", location="1")


@pytest.mark.parametrize("custom", [True, False])
@pytest.mark.parametrize("location", ["label", "object"])
def test_module_clearance_uses_physical_slot(driver, definition, rack_loader, custom, location):
    station = driver.stations["OT2"]
    module = Mock()
    module.load_labware.return_value = rack_loader.return_value
    module.load_labware_from_definition.return_value = rack_loader.return_value
    station.loaded_modules["temperature"] = module
    station._module_slots[id(module)] = "3"
    options = {"definition": definition} if custom else {"load_name": "standard_rack"}
    rack = station.load_labware(
        slot="temperature" if location == "label" else module,
        deck_clearance_mm=25, **options,
    )
    assert rack is rack_loader.return_value
    assert station._slot_deck_clearance_m == {"3": .025}
    rack_loader.assert_not_called()


@pytest.mark.parametrize("custom", [True, False])
def test_startup_loading_forwards_slot_clearance(monkeypatch, definition, custom):
    protocol = Mock()
    module = protocol.load_module.return_value
    rack = Mock()
    rack.wells_by_name.return_value = {"A1": Mock()}
    module.load_labware.return_value = rack
    module.load_labware_from_definition.return_value = rack
    monkeypatch.setattr(OT2, "_simulator_protocol", lambda self: protocol)
    options = {"definition": definition} if custom else {"load_name": "standard_rack"}
    station = OT2(
        module_definitions={"temperature": {"model": "temperatureModuleV1", "slot": "3"}},
        labware_definitions={"rack": {"location": "temperature", "deck_clearance_mm": 10, **options}},
    )
    assert station._slot_deck_clearance_m == {"3": .01}
    assert station.loaded_labware["rack"] is rack


def test_named_reload_with_margin_reuses_startup_module_labware(monkeypatch):
    protocol = Mock()
    module = protocol.load_module.return_value
    rack = module.load_labware.return_value
    rack.wells_by_name.return_value = {"A1": Mock()}
    monkeypatch.setattr(OT2, "_simulator_protocol", lambda self: protocol)
    station = OT2(
        module_definitions={"temperature_module": {"model": "temperatureModuleV1", "slot": "3"}},
        labware_definitions={"vial_rack": {"load_name": "standard_rack", "location": "temperature_module"}},
    )
    result = station.load_labware("standard_rack", "temperature_module", label="vial_rack", deck_clearance_mm=10)
    assert result is rack
    assert station._slot_deck_clearance_m == {"3": .01}
    module.load_labware.assert_called_once_with("standard_rack")


@pytest.mark.parametrize("changed", [
    {"load_name": "other_rack"}, {"slot": "2"}, {"namespace": "other"}, {"version": 2},
])
def test_named_reload_cannot_change_load_request_while_updating_margin(driver, rack_loader, changed):
    station = driver.stations["OT2"]
    protocol = station._simulator_protocol()
    protocol.load_labware.return_value = rack_loader.return_value
    options = {"load_name": "standard_rack", "slot": "1", "label": "rack",
               "namespace": "opentrons", "version": 1}
    station.load_labware(**options, deck_clearance_mm=5)
    with pytest.raises(ValueError, match="already registered"):
        station.load_labware(**{**options, **changed}, deck_clearance_mm=10)
    assert station._slot_deck_clearance_m == {"1": .005}
    assert protocol.load_labware.call_count == 1


def test_duplicate_named_load_without_margin_keeps_existing_rejection(driver, rack_loader):
    station = driver.stations["OT2"]
    protocol = station._simulator_protocol()
    protocol.load_labware.return_value = rack_loader.return_value
    station.load_labware("standard_rack", "1", label="rack")
    with pytest.raises(ValueError, match="already registered"):
        station.load_labware("standard_rack", "1", label="rack")
    assert protocol.load_labware.call_count == 1


def load_module(driver, **options):
    return driver.execute(
        task_name="station_operation", station="OT2", operation="load_module",
        **{"model": "temperatureModuleV1", "slot": "3", "label": "temperature_module", **options},
    )


def test_runtime_module_and_rack_registration_from_an_empty_deck(driver, definition, rack_loader):
    station = driver.stations["OT2"]
    protocol = station._simulator_protocol()
    module = protocol.load_module.return_value
    module.load_labware_from_definition.return_value = rack_loader.return_value
    assert station.loaded_modules == station.loaded_labware == {}

    result = load_module(driver)
    assert json.loads(json.dumps(result)) == {
        "name": "temperature_module", "slot": "3", "model": "temperatureModuleV1",
    }
    assert station.loaded_modules["temperature_module"] is module
    protocol.load_module.assert_called_once_with("temperatureModuleV1", "3")

    rack = load_rack(driver, definition, slot="temperature_module", deck_clearance_mm=10)
    assert rack == {"name": "rack", "slot": "3", "wells": ["A1", "B1"], "deck_clearance_mm": 10}
    assert station.resolve_address("3A1") is rack_loader.return_value.wells_by_name()["A1"]
    module.load_labware_from_definition.assert_called_once_with(definition, label="rack")
    rack_loader.assert_not_called()

    # A second setup run can reuse the module even with its rack already mounted.
    assert load_module(driver, slot=3) == result
    assert station.load_module("temperatureModuleV1", "3", label="temperature_module") is module
    assert protocol.load_module.call_count == 1


@pytest.mark.parametrize("options", [
    {"model": "magneticModuleV2"}, {"slot": "4"}, {"label": "another_module"},
])
def test_conflicting_runtime_module_load_preserves_the_existing_registration(driver, rack_loader, options):
    load_module(driver)
    with pytest.raises(ValueError, match="already registered|occupied"):
        load_module(driver, **options)
    station = driver.stations["OT2"]
    assert list(station.loaded_modules) == ["temperature_module"]
    assert station._simulator_protocol().load_module.call_count == 1


def test_module_cannot_be_loaded_into_a_labware_slot(driver, definition, rack_loader):
    load_rack(driver, definition, slot="3")
    with pytest.raises(ValueError, match="occupied"):
        load_module(driver)
    driver.stations["OT2"]._simulator_protocol().load_module.assert_not_called()


@pytest.mark.parametrize("options", [
    {"model": ""}, {"model": None}, {"slot": True}, {"slot": 0}, {"slot": 13},
])
def test_invalid_module_requests_do_not_reach_the_simulator(driver, rack_loader, options):
    with pytest.raises(ValueError, match="model|deck slot"):
        load_module(driver, **options)
    driver.stations["OT2"]._simulator_protocol().load_module.assert_not_called()


def test_module_simulation_failure_leaves_the_registry_empty(driver, rack_loader):
    protocol = driver.stations["OT2"]._simulator_protocol()
    protocol.load_module.side_effect = RuntimeError("invalid model")
    with pytest.raises(RuntimeError, match="invalid model"):
        load_module(driver)
    station = driver.stations["OT2"]
    assert station.loaded_modules == station._module_slots == station._named_module_requests == {}


def test_held_vial_prevents_runtime_module_loading(driver, rack_loader):
    driver.arm._attachment = Attachment(Vial("held"), (0.,) * 6)
    with pytest.raises(ValueError, match="before picking up"):
        load_module(driver)
    driver.stations["OT2"]._simulator_protocol().load_module.assert_not_called()


def test_paused_handoff_prevents_runtime_module_loading(driver, rack_loader):
    station = driver.stations["OT2"]
    driver.arm._set_station_context(
        station, "placement", Vial("paused"), "3A1", (0.,) * 6,
        ((0.,) * 7,), "vertical", (), release_allowed=True,
    )
    with pytest.raises(RuntimeError, match="paused"):
        load_module(driver)
    station._simulator_protocol().load_module.assert_not_called()
