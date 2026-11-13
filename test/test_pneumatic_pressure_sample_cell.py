import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from AFL.automation.loading.PneumaticPressureSampleCell import (
    PneumaticPressureSampleCell,
)


def test_robot_door_status_is_logged_only_when_it_changes(monkeypatch):
    cell = object.__new__(PneumaticPressureSampleCell)
    cell.digitalin = None
    cell.robot_interlock_url = "http://piot2:31950/robot/door/status"
    cell._last_robot_door_state = None
    cell.log_debug = Mock()

    states = iter(["closed", "closed", "open", "open"])

    class Response:
        def json(self):
            return {"data": {"status": next(states)}}

    get = Mock(return_value=Response())
    monkeypatch.setattr(
        "AFL.automation.loading.PneumaticPressureSampleCell.requests.get",
        get,
    )

    assert [cell._door_state() for _ in range(4)] == [False, False, True, True]
    assert cell.log_debug.call_args_list == [
        call(f"Robot door status at {cell.robot_interlock_url}: closed"),
        call(f"Robot door status at {cell.robot_interlock_url}: open"),
    ]
    assert get.call_count == 4
    get.assert_called_with(
        cell.robot_interlock_url,
        headers={"Opentrons-Version": "2"},
    )


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]

    def advance(delay):
        now[0] = round(now[0] + delay, 10)

    sleep = Mock(side_effect=advance)
    monkeypatch.setattr(
        "AFL.automation.loading.PneumaticPressureSampleCell.time.monotonic",
        lambda: now[0],
    )
    monkeypatch.setattr(
        "AFL.automation.loading.PneumaticPressureSampleCell.time.sleep", sleep
    )
    return now, sleep


@pytest.fixture
def interlocked_cell():
    cell = object.__new__(PneumaticPressureSampleCell)
    cell._app = None
    cell.state = "FRESH"
    cell.config = {"enforce_door_closed": True, "arm_move_delay": 0.2}
    cell._USE_DOOR_INTERLOCK = True
    cell._USE_ARM_LIMITS = False
    cell.digitalin = None
    cell.robot_interlock_url = "http://piot2:31950/robot/door/status"
    cell.relayboard = Mock()
    cell.log_warning = Mock()
    cell.log_info = Mock()
    return cell


def test_startup_reports_door_wait_before_sleep_and_periodically(clock, caplog):
    now, sleep = clock
    digitalin = SimpleNamespace(state={"DOOR": False})
    relayboard = Mock(labels={})
    caplog.set_level(logging.INFO)

    def wait_for_door(delay):
        if not digitalin.state["DOOR"]:
            assert "Arm motion blocked: door reports OPEN" in caplog.text
            assert not any(
                "arm-up" in args.args[0] for args in relayboard.setChannels.call_args_list
            )
        now[0] = round(now[0] + delay, 10)
        if now[0] >= 10.2:
            digitalin.state["DOOR"] = True

    sleep.side_effect = wait_for_door
    cell = PneumaticPressureSampleCell(Mock(), relayboard, digitalin=digitalin)

    waiting = [
        record for record in caplog.records if "Arm motion blocked" in record.message
    ]
    assert len(waiting) == 3
    for record, elapsed in zip(waiting, ["0.0", "5.0", "10.0"]):
        assert record.levelno == logging.WARNING
        assert f"{elapsed} s elapsed" in record.message
        assert "digital input DOOR" in record.message
        assert "Close the door to continue; this wait has no timeout." in record.message
        assert "the API server will not start until initialization completes" in record.message
    closed = [record for record in caplog.records if "Door reports CLOSED" in record.message]
    assert len(closed) == 1
    assert closed[0].levelno == logging.WARNING
    assert "after 10.2 s; resuming arm motion" in closed[0].message
    assert cell.app is None
    assert cell.state == "READY"
    assert cell.arm_state == "UP"
    relayboard.setChannels.assert_called_with(
        {"piston-vent": True, "arm-up": True, "arm-down": False}
    )


def test_runtime_door_wait_reports_source_and_restores_state(interlocked_cell, clock):
    cell = interlocked_cell
    cell._app = Mock()
    cell.state = "PREPARING TO LOAD"
    cell._door_state = Mock(side_effect=[True, True, False])

    cell._arm_interlock_check()

    cell.log_warning.assert_called_once()
    warning = cell.log_warning.call_args.args[0]
    assert cell.robot_interlock_url in warning
    assert "Driver initialization" not in warning
    cell.log_info.assert_called_once()
    assert "after 0.4 s; resuming arm motion" in cell.log_info.call_args.args[0]
    assert cell.state == "PREPARING TO LOAD"


def test_interrupted_startup_reports_reason_and_does_not_move_arm(interlocked_cell, clock):
    cell = interlocked_cell
    cell._door_state = Mock(return_value=True)
    _, sleep = clock
    sleep.side_effect = KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cell._arm_up()

    cell.relayboard.setChannels.assert_not_called()
    cell.log_info.assert_not_called()
    assert cell.state == "AWAITING DOOR CLOSED BEFORE MOVING ARM"
    assert cell.log_warning.call_count == 2
    assert "wait interrupted; arm motion was not started" in cell.log_warning.call_args.args[0]
    assert "the API server was not started" in cell.log_warning.call_args.args[0]


@pytest.mark.parametrize("mode", ["closed", "disabled", "no_interlock"])
def test_no_door_wait_preserves_existing_behavior(interlocked_cell, clock, mode):
    cell = interlocked_cell
    cell._door_state = Mock(return_value=False)
    if mode == "disabled":
        cell.config["enforce_door_closed"] = False
    elif mode == "no_interlock":
        cell._USE_DOOR_INTERLOCK = False

    cell._arm_interlock_check()

    _, sleep = clock
    sleep.assert_not_called()
    cell.log_info.assert_not_called()
    assert cell.state == "FRESH"
    if mode == "disabled":
        cell.log_warning.assert_called_once()
        assert "interlock check is disabled" in cell.log_warning.call_args.args[0]
    else:
        cell.log_warning.assert_not_called()
    if mode != "closed":
        cell._door_state.assert_not_called()


@pytest.fixture
def flow_cell(clock):
    now, _ = clock
    cell = object.__new__(PneumaticPressureSampleCell)
    cell._app = SimpleNamespace(logger=logging.getLogger("test.pneumatic_flow"))
    cell._data = {}
    cell.config = deepcopy(PneumaticPressureSampleCell.defaults)
    cell.config["load_timeout"] = 11
    cell.state = "READY"
    cell.arm_state = "UP"
    cell.rinse_status = "Not Rinsing"
    cell.digitalin = None
    cell._USE_DOOR_INTERLOCK = False
    cell._USE_ARM_LIMITS = False
    cell.loadStoppedExternally = False
    cell.load_stopper = []
    channels = dict.fromkeys(
        ["piston-vent", "postsample", "arm-up", "arm-down", "rinse1", "rinse2", "blow"],
        False,
    )
    cell.relayboard = Mock()
    cell.relayboard.setChannels.side_effect = channels.update
    cell.relayboard.getChannels.side_effect = lambda: dict(channels)
    cell.pctrl = Mock()
    deadline = [0]

    def timed_dispense(pressure, duration, block=True):
        deadline[0] = now[0] + duration

    cell.pctrl.timed_dispense.side_effect = timed_dispense
    cell.pctrl.dispenseRunning.side_effect = lambda: now[0] < deadline[0]
    return cell


def test_static_load_logs_progress_and_preserves_valve_sequence(flow_cell, caplog):
    cell = flow_cell
    caplog.set_level(logging.INFO)

    cell.loadSample(sampleVolume=0.3, load_dest_label="afterSANS")

    assert cell.state == "LOADED"
    assert cell.arm_state == "DOWN"
    cell.pctrl.timed_dispense.assert_called_once_with(2, 11, block=False)
    cell.pctrl.ramp_dispense.assert_not_called()
    assert cell.relayboard.setChannels.call_args_list == [
        call({"piston-vent": True, "postsample": False}),
        call({"piston-vent": True, "arm-up": False, "arm-down": True}),
        call({"piston-vent": False, "postsample": True}),
        call({"postsample": False}),
    ]
    assert "load_pressure=2" in caplog.text
    assert "LOAD IN PROGRESS to afterSANS" in caplog.text
    progress = [r.message for r in caplog.records if "loadSample progress:" in r.message]
    assert len(progress) == 3  # Once immediately, then every five seconds.
    assert "reason=configured dispense duration elapsed" in caplog.text
    assert "does not verify liquid arrival" in caplog.text
    assert "relay readback=" in caplog.text
    assert "loadSample completed" in caplog.text
    assert all(r.name == "test.pneumatic_flow" for r in caplog.records)


def test_load_logs_external_stop_before_duration_limit(flow_cell, clock, caplog):
    cell = flow_cell
    now, sleep = clock
    caplog.set_level(logging.INFO)

    def advance_and_stop(delay):
        now[0] = round(now[0] + delay, 10)
        if "LOAD IN PROGRESS" in cell.state and now[0] >= 3 and not cell.loadStoppedExternally:
            assert cell.stopLoad(secret="xrays>neutrons") == "Load stopped successfully."

    sleep.side_effect = advance_and_stop
    cell.loadSample()

    cell.pctrl.stop.assert_called_once()
    assert cell.state == "LOADED"
    assert cell._data["load_stop_source"] == "external"
    assert "reason=external stop received" in caplog.text
    assert "configured dispense duration elapsed" not in caplog.text
    assert "pressure controller stop command completed" in caplog.text
    assert "xrays>neutrons" not in caplog.text


def test_ramp_load_logs_settings_and_preserves_controller_arguments(flow_cell, caplog):
    cell = flow_cell
    cell.config.update(load_mode="ramp", load_timeout=60)
    caplog.set_level(logging.INFO)

    cell.loadSample()

    cell.pctrl.ramp_dispense.assert_called_once_with(2, 7, 60, const_time=40)
    cell.pctrl.timed_dispense.assert_not_called()
    assert "starting ramp from pressure=2 to 7 over 20 s, then holding for 40 s" in caplog.text
    assert "reason=pressure controller is no longer running" in caplog.text
    assert cell.state == "LOADED"


def test_load_logs_arm_timeout_before_applying_pressure(flow_cell, caplog):
    cell = flow_cell
    cell.digitalin = SimpleNamespace(state={"ARM_UP": True, "ARM_DOWN": True})
    cell._USE_ARM_LIMITS = True
    cell.config["arm_move_timeout"] = 0.3
    caplog.set_level(logging.INFO)

    with pytest.raises(TimeoutError, match="ARM_DOWN"):
        cell.loadSample()

    cell.pctrl.timed_dispense.assert_not_called()
    assert cell.state == "PREPARING TO LOAD"
    assert "input must become LOW (0)" in caplog.text
    assert "digital inputs=" in caplog.text
    assert "loadSample failed during lowering arm" in caplog.text
    assert "loadSample completed" not in caplog.text


def test_load_logs_regulator_failure_without_reporting_completion(flow_cell, caplog):
    cell = flow_cell
    error = OSError("LabJack output unavailable")
    cell.pctrl.timed_dispense.side_effect = error
    caplog.set_level(logging.INFO)

    with pytest.raises(OSError) as raised:
        cell.loadSample()

    assert raised.value is error
    assert "failed during starting pressure dispense" in caplog.text
    assert "OSError: LabJack output unavailable" in caplog.text
    assert cell.state == "LOAD IN PROGRESS"
    assert "loadSample completed" not in caplog.text


def test_diagnostic_readback_failure_does_not_interrupt_load(flow_cell, caplog):
    cell = flow_cell
    cell.relayboard.getChannels.side_effect = OSError("readback unavailable")
    caplog.set_level(logging.INFO)

    cell.loadSample()

    assert cell.state == "LOADED"
    assert "relay readback unavailable: OSError: readback unavailable" in caplog.text
    assert "loadSample completed" in caplog.text


@pytest.mark.parametrize("initial_state", ["LOADED", "READY"])
def test_rinse_logs_each_step_and_preserves_hardware_sequence(flow_cell, clock, caplog, initial_state):
    cell = flow_cell
    cell.state = initial_state
    cell.arm_state = "DOWN" if initial_state == "LOADED" else "UP"
    cell.config["rinse_program"] = [("rinse1", 1), (None, 0.5), ("rinse2", 1), ("ctrlblow", 1), ("blow", 1)]
    caplog.set_level(logging.INFO)

    if initial_state == "READY":
        with pytest.warns(UserWarning, match="Rinsing despite READY"):
            cell.rinseCell()
    else:
        cell.rinseCell()

    expected = [
        call({"piston-vent": False, "postsample": True}),
        call({"rinse1": True}), call({"rinse1": False}),
        call({"rinse2": True}), call({"rinse2": False}),
        call({"blow": True}), call({"blow": False}),
        call({"postsample": False}),
        call({"piston-vent": True, "arm-up": True, "arm-down": False}),
    ]
    if initial_state == "READY":
        expected.insert(0, call({"piston-vent": True, "arm-up": False, "arm-down": True}))
    assert cell.relayboard.setChannels.call_args_list == expected
    assert cell.pctrl.set_P.call_args_list == [call(20), call(0)]
    assert cell.state == "READY"
    assert cell.arm_state == "UP"
    assert cell.rinse_status == "Not Rinsing"
    for index, action in enumerate(["rinse1", "pause", "rinse2", "ctrlblow", "blow"], 1):
        assert f"rinseCell step {index}/5 ({action}): starting" in caplog.text
        assert f"rinseCell step {index}/5 ({action}): completed" in caplog.text
    assert "scheduled wait time=4.5 s" in caplog.text
    assert "commanding regulated pressure=20" in caplog.text
    assert "commanding regulated pressure=0" in caplog.text
    assert "rinseCell completed" in caplog.text


def test_rinse_failure_identifies_step_and_does_not_report_ready(flow_cell, caplog):
    cell = flow_cell
    cell.state = "LOADED"
    cell.arm_state = "DOWN"
    cell.config["rinse_program"] = [("ctrlblow", 1)]
    error = OSError("regulator disconnected")
    cell.pctrl.set_P.side_effect = error
    caplog.set_level(logging.INFO)

    with pytest.raises(OSError) as raised:
        cell.rinseCell()

    assert raised.value is error
    assert cell.state == "LOADED"
    assert "rinseCell failed during rinseCell step 1/1 (ctrlblow)" in caplog.text
    assert "OSError: regulator disconnected" in caplog.text
    assert "rinseCell completed" not in caplog.text
