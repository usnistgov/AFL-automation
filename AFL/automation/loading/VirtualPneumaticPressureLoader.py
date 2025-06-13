"""Virtual version of :mod:`PneumaticPressureSampleCell`.

This module defines no-op hardware classes and a ``VirtualPneumaticPressureLoader``
class that mimics the behaviour of
``PneumaticPressureSampleCell`` without touching any real devices.  The
interface is identical but actions merely update internal state and print
messages.  It is useful for testing launch scripts or running the loader logic
on systems without the required hardware.
"""

from AFL.automation.loading.PneumaticPressureSampleCell import (
    PneumaticPressureSampleCell,
)
from AFL.automation.loading.PressureController import PressureController
from AFL.automation.loading.MultiChannelRelay import MultiChannelRelay


class NoOpPressureController(PressureController):
    """Pressure controller that only records pressure state."""

    def __init__(self):
        self.current_pressure = 0
        self.active_callback = None
        self.app = None
        self.data = None

    def set_P(self, pressure):
        self.current_pressure = pressure
        print(f"[NoOpPressureController] Set pressure to {pressure}")


class NoOpRelayBoard(MultiChannelRelay):
    """Relay board that only tracks channel state."""

    def __init__(self, labels=None):
        labels = labels or {}
        self.labels = {int(k): v for k, v in labels.items()}
        self.ids = {v: int(k) for k, v in self.labels.items()}
        self.state = {name: False for name in self.labels.values()}
        self.app = None
        self.data = None

    def setChannels(self, channels):
        for key, val in channels.items():
            name = key if isinstance(key, str) else self.labels.get(key, key)
            self.state[name] = val
            print(f"[NoOpRelayBoard] Set {name} -> {val}")

    def getChannels(self, asid=False):
        if asid:
            return {i: self.state[name] for i, name in self.labels.items()}
        return dict(self.state)

    def toggleChannels(self, channels):
        for key in channels:
            name = key if isinstance(key, str) else self.labels[key]
            self.state[name] = not self.state[name]
            print(f"[NoOpRelayBoard] Toggled {name} -> {self.state[name]}")


class NoOpDigitalIn:
    """Digital input class that simply stores pin state."""

    def __init__(self, channels=None, pull_dir="UP"):
        channels = channels or {}
        self.channels = {int(k): v for k, v in channels.items()}
        self.ids = {v: int(k) for k, v in self.channels.items()}
        self.state = {name: False for name in self.channels.values()}


class VirtualPneumaticPressureLoader(PneumaticPressureSampleCell):
    """Virtual loader using no-op hardware classes."""

    def __init__(self, pctrl=None, relayboard=None, digitalin=None, **kwargs):
        pctrl = pctrl or NoOpPressureController()
        relayboard = relayboard or NoOpRelayBoard()
        if isinstance(digitalin, dict):
            digitalin = NoOpDigitalIn(digitalin)

        super().__init__(
            pctrl,
            relayboard,
            digitalin=digitalin,
            **kwargs,
        )


_DEFAULT_CUSTOM_CONFIG = {
    '_classname': 'AFL.automation.loading.VirtualPneumaticPressureLoader.VirtualPneumaticPressureLoader',
    '_args': [
        {'_classname': 'AFL.automation.loading.VirtualPneumaticPressureLoader.NoOpPressureController'},
        {
            '_classname': 'AFL.automation.loading.VirtualPneumaticPressureLoader.NoOpRelayBoard',
            '_args': [{
                7: 'arm-up', 6: 'arm-down',
                1: 'rinse1', 2: 'rinse2', 3: 'blow',
                4: 'piston-vent', 5: 'postsample'
            }]
        }
    ],
    # Digital inputs can be added if needed, but by default the virtual loader
    # operates without them so arm limit and door interlock checks are skipped.
    'load_stopper': []
}
