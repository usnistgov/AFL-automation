import opentrons.execute

from NistoRoboto.OT2App.DoorDaemon import DoorDaemon
from NistoRoboto.OT2App.OT2Protocol import OT2Protocol

import threading
import time
import datetime

class OT2Daemon(threading.Thread):
    '''
    '''
    def __init__(self,app,task_queue,debug_mode=True):
        app.logger.info('Creating OT2Daemon thread')

        threading.Thread.__init__(self,name='OT2Daemon',daemon=True)

        self.protocol  = OT2Protocol(app)

        self.doorDaemon = DoorDaemon(app,task_queue)
        self.doorDaemon.start()

        self._stop = False
        self._app = app
        self.task_queue = task_queue
        self.debug_mode = debug_mode

    def terminate(self):
        self.doorDaemon.terminate()

        self._app.logger.info('Terminating OT2Daemon thread')
        self._stop = True
        self.task_queue.put(None)

    def run(self):
        while not self._stop:
            # this will block until something enters the task_queue
            task = self.task_queue.get(block=True,timeout=None)
            self._app.logger.info(f'Running task {task}')

            # Queue execution mods
            if task is None: #stop the queue execution
                self.terminate()
                break
            elif 'debug_mode' in task: #modify the debugging mode state
                self._app.logger.debug(f'Setting queue debug_mode to {task["debug_mode"]}')
                self.debug_mode = task['debug_mode']
                continue
            elif self.debug_mode: #if debug_mode, pop but don't execute
                time.sleep(2.0)
                continue

            #safety interlock
            counter = 600
            while not self.doorDaemon.door_closed:
                time.sleep(0.1)

                counter += 1
                if counter>600:
                    self._app.logger.info(f'Queue is paused. Please close OT-2 door to resume.')
                    counter=0

            if task['type'] == 'transfer':
                self.protocol.transfer(**task)
            elif task['type'] == 'load_labware':
                self.protocol.load_labware(**task)
            elif task['type'] == 'load_instrument':
                self.protocol.load_instrument(**task)
            elif task['type'] == 'reset':
                self.protocol.reset()
            elif task['type'] == 'home':
                self.protocol.home()
            else:
                raise ValueError(f'Task type not recognized: {task["type"]}')
            time.sleep(0.1)

        self._app.logger.info('OT2Daemon runloop exiting')

    







