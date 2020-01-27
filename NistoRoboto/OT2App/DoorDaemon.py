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
        self.button_color = '#000000'

    def terminate(self):
        self._app.logger.info('Terminating DoorDaemon thread')
        self._stop = True

    def set_button_light(self,red=False,green=False,blue=False):
        gpio.set_button_light(red=red,green=green,blue=blue)
        self.button_color = '#'+('ff' if red else '00')+('ff' if green else '00')+('ff' if blue else '00')

    @property
    def door_closed(self):
        return gpio.read_window_switches()

    def run(self):
        while not self._stop:
            # put other logic about safety state here, other sensors, etc.
            self.safe = self.door_closed  
            self.pendtask = (not self.task_queue.empty())

            # this is a crude watchdog timer mechanic, clients should check
            # this relative to their datetime.now and refuse to believe the
            # interlock value if data stale.
            self.last_check = datetime.datetime.now()  

            if(self.safe):
                if self.pendtask:  
                    #red = running and not safe to enter!
                    self.set_button_light(red=True)
                else:
                    #green = not running, safe to enter, ready to run!
                    self.set_button_light(green=True)
            else:
                #blue = window is open! will not run!
                self.set_button_light(blue=True)

            time.sleep(0.1)
        self._app.logger.info('DoorDaemon runloop exiting')
