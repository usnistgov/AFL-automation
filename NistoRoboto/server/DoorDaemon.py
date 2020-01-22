import threading
import time
from opentrons.drivers.rpi_drivers import gpio


class DoorDaemon(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self,daemon=True)
        self._stop = False
        self._open = True

    @property
    def is_open(self):
        return self._open

    def terminate(self):
        self._stop = True

    def run(self):
        while not self._stop:
            if gpio.read_window_switches():
                #window is closed! green = safe!
                gpio.set_button_light(green=True,red=False,blue=False)
                self._open=False
            else:
                #window is open! red = caution!
                gpio.set_button_light(green=False,red=True,blue=False)
                self._open=True
            time.sleep(0.1)
