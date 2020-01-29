import threading
import time
import datetime

class QueueDaemon(threading.Thread):
    '''
    '''
    def __init__(self,app,task_queue,history,debug_mode=True):
        app.logger.info('Creating QueueDaemon thread')

        threading.Thread.__init__(self,name='QueueDaemon',daemon=True)

        self.protocol  = None#Protocol(app)

        self._stop = False
        self._app = app
        self.task_queue = task_queue
        self.history    = history
        self.debug_mode = debug_mode

    def terminate(self):
        self._app.logger.info('Terminating QueueDaemon thread')
        self._stop = True
        self.task_queue.put(None)

    def run(self):
        while not self._stop:
            task = self.task_queue.get(block=True,timeout=None)
            self._app.logger.info(f'Running task {task}')
            task['end'] = datetime.datetime.now().strftime('%H:%M')
            self.history.append(task)

            # Queue execution mods
            if task is None: #stop the queue execution
                self.terminate()
                break
            elif 'debug_mode' in task: #modify the debugging mode state
                self._app.logger.debug(f'Setting queue debug_mode to {task["debug_mode"]}')
                self.debug_mode = task['debug_mode']
                continue
            elif self.debug_mode: #if debug_mode, pop but don't execute
                time.sleep(3.0)
                continue

            continue
            getattr(self.protocol,task['name'])(**task)
            time.sleep(0.1)

        self._app.logger.info('QueueDaemon runloop exiting')

    







