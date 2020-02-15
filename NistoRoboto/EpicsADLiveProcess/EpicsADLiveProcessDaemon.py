import queue
import threading
import time
import datetime

class EpicsADLiveProcessDaemon(threading.Thread):
    '''
    Overall EPICS AD interface

    spawns two main threads: collateDaemon and reduceDaemon
        also holds the instance of EpicsAD that this all talks to (or does that sit in collateDaemon?)

    flow: EpicsAD has callbacks hooked to detector params that auto-fire on change.

    the callback responders are strong interrupts, so need to be **fast**, so they just shove the raw event data into a queue

    collatedaemon tracks the state of the detector internally, changes it according to events in the queue, and when a new 
    image arrives, it puts it into the ReduceDaemon queue.  

    ReduceDaemon runs the data through whatever reduction routines you specify (from just making a log-scale jpeg to fully
    reducing with pyfai and classifying with ML.)


    '''
    def __init__(self,app,task_queue,debug_mode=True):
        app.logger.info('Creating EpicsADLiveProcessDaemon thread')

        threading.Thread.__init__(self,name='EpicsADLiveProcessDaemon',daemon=True)

        self.reduction_queue = queue.Queue()

        self.collateDaemon = CollateDaemon(app,reduction_queue)
        self.collateDaemon.start()

        self.reduceDaemon = ReduceDaemon(app,reduction_queue)
        self.reduceDaemon.start()

        self._stop = False
        self._app = app
        self.task_queue = task_queue
        self.debug_mode = debug_mode

    def terminate(self):
        self.collateDaemon.terminate()
        self.reduceDaemon.terminate()

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

        self._app.logger.info('EpicsADLiveProcessDaemon runloop exiting')

    







