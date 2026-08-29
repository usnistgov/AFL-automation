import logging

from AFL.automation.loading.PressureController import PressureController


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
