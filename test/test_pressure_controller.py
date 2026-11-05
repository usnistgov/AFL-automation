import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from AFL.automation.loading.PressureController import PressureController
from AFL.automation.loading.DigitalOutPressureController import DigitalOutPressureController


class _Callback:
    def __init__(self):
        self.cancelled = False

    def is_alive(self):
        return not self.cancelled

    def cancel(self):
        self.cancelled = True


class _PressureController(PressureController):
    def __init__(self):
        self.active_callback = _Callback()
        self.pressures = []

    def set_P(self, pressure):
        self.pressures.append(pressure)


def test_stop_uses_logging_instead_of_print(caplog, capsys):
    controller = _PressureController()
    caplog.set_level(
        logging.INFO,
        logger='AFL.automation.loading.PressureController',
    )

    controller.stop()

    assert 'Stopping pressure dispense; callback running=True' in caplog.text
    assert controller.pressures == [0]
    assert controller.active_callback.cancelled is True
    assert capsys.readouterr().out == ''


def test_timed_dispense_and_stop_log_to_attached_api_logger(monkeypatch, caplog):
    output = Mock(port_to_write="TDAC4")
    controller = DigitalOutPressureController(output, 3)
    controller.app = SimpleNamespace(logger=logging.getLogger("test.pressure_api"))
    callback = _Callback()
    callback.start = Mock()
    timer = Mock(return_value=callback)
    monkeypatch.setattr("AFL.automation.loading.PressureController.threading.Timer", timer)
    caplog.set_level(logging.DEBUG)

    controller.timed_dispense(2, 60, block=False)
    timer.call_args.args[1]()  # Execute the stop callback without waiting or using hardware.

    timer.assert_called_once_with(60, controller.stop)
    callback.start.assert_called_once()
    assert callback.cancelled is True
    assert [c.args[0] for c in output.write.call_args_list] == [2 / 3, 0]
    assert "Starting timed pressure dispense: pressure=2, duration=60 s" in caplog.text
    assert "commanded_voltage=0.666667 V, port=TDAC4" in caplog.text
    assert "zero-pressure command completed" in caplog.text
    assert all(r.name == "test.pressure_api" for r in caplog.records)


def test_failed_output_write_logs_conversion_and_keeps_original_exception(caplog):
    output = Mock(port_to_write="TDAC4")
    error = OSError("interval handle not initialized")
    output.write.side_effect = error
    controller = DigitalOutPressureController(output, 3)
    controller.app = SimpleNamespace(logger=logging.getLogger("test.pressure_api"))
    caplog.set_level(logging.DEBUG)

    with pytest.raises(OSError) as raised:
        controller.set_P(2)

    assert raised.value is error
    assert "waiting for output write" in caplog.text
    assert "Pressure output failed: requested_pressure=2" in caplog.text
    assert "conversion=3 pressure units/V, port=TDAC4" in caplog.text
    assert "interval handle not initialized" in caplog.text
    assert "Pressure output write completed" not in caplog.text


def test_ramp_progress_is_periodic_and_uses_api_logger(monkeypatch, caplog):
    controller = _PressureController()
    controller.app = SimpleNamespace(logger=logging.getLogger("test.pressure_api"))
    controller.start_time = 0
    stop_flag = threading.Event()
    now = [0]

    def advance(delay):
        now[0] = round(now[0] + delay, 10)
        if now[0] >= 6:
            stop_flag.set()

    monkeypatch.setattr("AFL.automation.loading.PressureController.time.time", lambda: now[0])
    monkeypatch.setattr("AFL.automation.loading.PressureController.time.sleep", advance)
    caplog.set_level(logging.INFO)

    controller._ramp_pressure(2, 7, 20, 10, stop_flag)

    progress = [r.message for r in caplog.records if "Pressure ramp progress:" in r.message]
    assert len(progress) == 2
    assert "elapsed=0.0 s" in progress[0]
    assert "elapsed=5.0 s" in progress[1]
    assert "reason=external stop flag" in caplog.text
    assert controller.pressures[-1] == 0
    assert all(r.name == "test.pressure_api" for r in caplog.records)


def test_ramp_thread_reports_output_failure_to_api_logger(caplog):
    controller = _PressureController()
    controller.app = SimpleNamespace(logger=logging.getLogger("test.pressure_api"))
    controller.start_time = time.time()
    error = OSError("pressure write failed")
    controller.set_P = Mock(side_effect=error)
    caplog.set_level(logging.INFO)

    with pytest.raises(OSError) as raised:
        controller._ramp_pressure(2, 7, 20, 10, threading.Event())

    assert raised.value is error
    assert "Pressure ramp thread failed: OSError: pressure write failed" in caplog.text
