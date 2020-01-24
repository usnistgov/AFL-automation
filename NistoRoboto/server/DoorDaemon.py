import threading
import time
from opentrons.drivers.rpi_drivers import gpio


class DoorDaemon(threading.Thread):
    def __init__(self,app,task_queue):
        app.logger.info('Creating DoorDaemon thread')

        threading.Thread.__init__(self,daemon=True)
        self._stop = False
        self._app = app
        self.task_queue = task_queue

    def terminate(self):
        self._app.logger.info('Terminating DoorDaemon thread')
        self._stop = True

    def set_button_light(self,red=False,green=False,blue=False):
        red_state,green_state,blue_state = gpio.get_button_light()
        if not ((red_state == red) and (blue_state==blue) and (green_state==green)):
            origin = f'({red_state},{green_state},{blue_state})'
            dest = f'({red},{green},{blue})'
            self._app.logger.debug(f'Button rgb from {origin} to {dest}')
            gpio.set_button_light(red=red,green=green,blue=blue)

    @property
    def door_closed(self):
        return gpio.read_window_switches()

    def run(self):
        while not self._stop:
            if self.door_closed:
                if self.task_queue.empty():
                    #green = safe and ready to run!
                    self.set_button_light(green=True)
                    
                else:
                    #blue = safe and runing!
                    self.set_button_light(blue=True)
            else:
                #window is open! red = caution!
                self.set_button_light(red=True)
            time.sleep(0.1)
        self._app.logger.info('DoorDaemon runloop exiting')