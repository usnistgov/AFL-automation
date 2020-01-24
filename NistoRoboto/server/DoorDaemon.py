import threading
import time
from opentrons.drivers.rpi_drivers import gpio
import datetime


class DoorDaemon(threading.Thread):
    def __init__(self,app,task_queue):
        app.logger.info('Creating DoorDaemon thread')

        threading.Thread.__init__(self,name='DoorDaemon',daemon=True)
        self._stop = False
        self._app = app
        self.task_queue = task_queue

    def terminate(self):
        self._app.logger.info('Terminating DoorDaemon thread')
        self._stop = True

    def set_button_light(self,red=False,green=False,blue=False):
        red_state,green_state,blue_state = gpio.get_button_light()
        if not ((red_state == red) and (blue_state==blue) and (green_state==green)):
            # origin = f'({red_state},{green_state},{blue_state})'
            # dest = f'({red},{green},{blue})'
            # self._app.logger.debug(f'Button rgb from {origin} to {dest}')
            gpio.set_button_light(red=red,green=green,blue=blue)

    @property
    def door_closed(self):
        return gpio.read_window_switches()

    def run(self):
        while not self._stop:
            self.safe = self.door_closed  # put other logic about safety state here, other sensors, etc.
            self.pendtask = not self.task_queue.empty()
            self.last_check = datetime.datetime.now()  # this is a crude watchdog timer mechanic, clients should check this relative to their datetime.now
                                              # and refuse to believe the interlock value if data stale.


            if(self.safe):
                if self.pendtask:  # proposed color reorg: blue = door open and interlock blocked, red = not safe to open door (running), green = safe to open door (not running)
                    #blue = safe and runing!
                    self.set_button_light(red=True)
                else:
                    #green = safe and ready to run!
                    self.set_button_light(green=True)
            else:
                #window is open! red = caution!
                self.set_button_light(blue=True)

            time.sleep(0.1)
        self._app.logger.info('DoorDaemon runloop exiting')
