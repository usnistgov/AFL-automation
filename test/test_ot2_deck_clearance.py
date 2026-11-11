"""Exercise deck clearances with native-like geometry and no hardware commands."""

import logging
import math
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from AFL.automation.manipulate.ufactory_xarm.labware import Vial
from AFL.automation.manipulate.ufactory_xarm.stations import OT2
from AFL.automation.manipulate.ufactory_xarm.ufactory import xArmManipulator


def slot_definition(slot):
    # Dimensions and spacing from the Opentrons ot2_standard v3 deck.
    column, row = (int(slot) - 1) % 3, (int(slot) - 1) // 3
    return {"position": [132.5 * column, 90.5 * row, 0],
            "boundingBox": {"xDimension": 128, "yDimension": 86, "zDimension": 0}}


def native_rack(slot, height_mm):
    origin = slot_definition(slot)["position"]
    wells = {}
    for name, dz in (("A1", 0), ("B1", 2)):
        point = SimpleNamespace(x=origin[0] + 40, y=origin[1] + 50, z=height_mm + dz)
        wells[name] = SimpleNamespace(top=Mock(return_value=SimpleNamespace(point=point)))
    return SimpleNamespace(wells_by_name=lambda: wells)


@pytest.fixture
def deck(monkeypatch):
    station = OT2()
    station.deck_rotation = np.eye(3)
    station.deck_translation = (0., 0., .12)
    racks = {"1": native_rack("1", 50), "2": native_rack("2", 100),
             "3": native_rack("3", 160), "6": native_rack("6", 380)}
    protocol = Mock()
    protocol.deck.get_slot_definition.side_effect = slot_definition
    protocol.load_labware.side_effect = lambda name, location: racks[location]
    monkeypatch.setattr(station, "_simulator_protocol", lambda: protocol)
    for slot in racks:
        station.load_labware(f"rack{slot}", slot, deck_clearance_mm=5 if slot == "1" else None)
    return station, protocol


@pytest.fixture
def motion_arm(deck, monkeypatch):
    station, _ = deck
    arm = xArmManipulator(simulation=True, stations=[station])
    arm.test_entry = (-.05, -.05, .1, 3.1, -.02, 1.5)
    arm.test_moves = []
    arm.test_entries = []

    def enter(*args, **kwargs):
        arm.test_entries.append(kwargs)
        arm._current_station = station.name
        arm._last_tcp_pose = arm.test_entry
        return arm.test_entry

    def move(target, *args, **kwargs):
        arm.test_moves.append(tuple(target))
        arm._last_tcp_pose = tuple(target)

    monkeypatch.setattr(arm, "_enter", enter)
    monkeypatch.setattr(arm, "_move_pose", move)
    monkeypatch.setattr(arm, "_read_tcp", lambda: arm._last_tcp_pose)
    return arm


def pickup(arm, location="1A1", *, retreat=False):
    result = arm.station_operation(
        "OT2", "pick", labware=Vial("vial", height_mm=50), location=location,
        grasp=25, retreat=retreat,
    )
    assert result["success"], result
    return result


def vertical_moves(moves):
    return [(before, after) for before, after in zip(moves, moves[1:])
            if before[:2] == after[:2] and after[2] > before[2]]


def test_slot_height_uses_highest_well_in_only_that_slot(deck):
    station, _ = deck
    assert station.loaded_labware_max_z("1") == pytest.approx(.172)
    assert station.loaded_labware_max_z("3") == pytest.approx(.282)
    assert station.loaded_labware_max_z() == pytest.approx(.502)


def test_pickup_retreat_excludes_unrelated_tall_modules(deck, motion_arm, caplog):
    station, _ = deck
    with caplog.at_level(logging.INFO):
        pickup(motion_arm)
    context = motion_arm._station_context
    # 172 mm rack top + 5 mm slot margin + 50 mm carried vial.
    assert context.retreat_waypoints[0] == pytest.approx((.04, .05, .227))
    assert all(waypoint[2] == pytest.approx(.227) for waypoint in context.retreat_waypoints)
    assert "well-top Z 172.000 mm + margin 5.000 mm + carried height 50.000 mm" in caplog.text
    motion_arm.test_moves.clear()
    result = motion_arm.retreat()
    assert result["success"], result
    assert motion_arm.test_moves[0][:3] == pytest.approx((.04, .05, .227))
    assert all(move[3:] == motion_arm.test_entry[3:] for move in motion_arm.test_moves)


def test_immediate_pickup_retreat_executes_slot_height(motion_arm):
    pickup(motion_arm, retreat=True)
    assert motion_arm._station_context is None
    assert max(move[2] for move in motion_arm.test_moves) == pytest.approx(.227)
    assert all(move[3:] == motion_arm.test_entry[3:] for move in motion_arm.test_moves)


def test_retreat_raises_at_crossed_slots_after_local_lift(deck, motion_arm):
    station, _ = deck
    motion_arm.test_entry = (.45, -.05, .1, *motion_arm.test_entry[3:])
    pickup(motion_arm)
    route = motion_arm._station_context.retreat_waypoints
    assert route[0] == pytest.approx((.04, .05, .227))
    lifts = vertical_moves(route)
    # Unspecified crossed slots use their own height plus the 15 mm YAML margin.
    assert lifts[0][0] == pytest.approx((.1325, .05, .227))
    assert lifts[0][1] == pytest.approx((.1325, .05, .287))
    assert lifts[1][0] == pytest.approx((.265, .05, .287))
    assert lifts[1][1] == pytest.approx((.265, .05, .347))
    # Slot 6 is taller but lies in another row, outside both lateral legs.
    assert max(waypoint[2] for waypoint in route) == pytest.approx(.347)


def test_temp_placement_adopts_temp_clearance_near_its_slot(deck, motion_arm):
    station, _ = deck
    station._slot_deck_clearance_m["3"] = .03
    pickup(motion_arm, retreat=True)
    motion_arm.test_moves.clear()
    result = motion_arm.station_operation("OT2", "place", location="3A1", release=True)
    assert result["success"], result
    moves = motion_arm.test_moves
    assert moves[0][:3] == pytest.approx((-.05, -.05, .15))
    lifts = vertical_moves(moves)
    assert lifts[-1][0][:3] == pytest.approx((.265, .05, .287))
    assert lifts[-1][1][:3] == pytest.approx((.265, .05, .362))
    assert moves[-1][:3] == pytest.approx((.305, .05, .28))
    assert motion_arm.attached_labware is None
    # The saved route remains conservative after release, as before this change.
    assert motion_arm._station_context.retreat_waypoints[0] == pytest.approx((.305, .05, .362))
    result = motion_arm.retreat()
    assert result["success"], result
    assert motion_arm._station_context is None


@pytest.mark.parametrize("tagged, expected_z", [(True, .227), (False, .567)])
def test_explicit_xyz_uses_slot_tag_or_deck_wide_fallback(motion_arm, tagged, expected_z):
    location = {"link_base_mm": [40, 50, 170]}
    if tagged:
        location["slot"] = 1
    pickup(motion_arm, location)
    assert motion_arm._station_context.retreat_waypoints[0][2] == pytest.approx(expected_z)


def test_legacy_loads_keep_the_original_global_route(deck, motion_arm):
    station, protocol = deck
    station._slot_deck_clearance_m.clear()
    protocol.deck.get_slot_definition.side_effect = AssertionError("legacy route must not need slot metadata")
    pickup(motion_arm)
    np.testing.assert_allclose(motion_arm._station_context.retreat_waypoints,
                               ((.04, .05, .567), (-.05, .05, .567), (-.05, -.05, .567)))


def test_deck_wide_fallback_honors_a_larger_slot_margin(deck, motion_arm):
    station, _ = deck
    station._slot_deck_clearance_m["1"] = .7
    pickup(motion_arm, {"link_base_mm": [40, 50, 170]})
    assert motion_arm._station_context.retreat_waypoints[0][2] == pytest.approx(.922)


def test_missing_slot_geometry_fails_before_arm_entry(deck, motion_arm):
    _, protocol = deck
    protocol.deck.get_slot_definition.side_effect = KeyError("missing slot")
    result = motion_arm.station_operation("OT2", "pick", labware=Vial("vial"), location="1A1")
    assert result["success"] is False
    assert "footprint" in result["message"]
    assert motion_arm.test_entries == motion_arm.test_moves == []


@pytest.mark.parametrize("slot", [True, "0", 13, "temperature", 12])
def test_invalid_or_unloaded_explicit_slot_is_rejected(deck, slot):
    station, _ = deck
    with pytest.raises(ValueError, match="slot"):
        station.resolve_address({"link_base_mm": [40, 50, 170], "slot": slot})


def test_slot_footprint_includes_deck_tilt_at_loaded_height(deck):
    station, _ = deck
    angle = math.radians(10)
    station.deck_rotation = np.array(((math.cos(angle), 0, math.sin(angle)),
                                     (0, 1, 0), (-math.sin(angle), 0, math.cos(angle))))
    x_bounds, y_bounds = station._slot_xy_bounds("1")
    assert x_bounds == pytest.approx((0, .128 * math.cos(angle) + .052 * math.sin(angle)))
    assert y_bounds == pytest.approx((0, .086))


@pytest.mark.parametrize("start,end,expected", [
    ((0, .05), (.4, .05), .1325 / .4),
    ((.4, .05), (0, .05), (.4 - .2605) / .4),
    ((.2, -.1), (.2, .2), .1 / .3),
    ((0, .2), (.4, .2), None),
    ((.2, .05), (.2, .05), 0),
])
def test_slot_crossings_handle_both_axes_and_direction(start, end, expected):
    fraction = OT2._slot_crossing(start, end, ((.1325, .2605), (0, .086)))
    assert fraction == (None if expected is None else pytest.approx(expected))
