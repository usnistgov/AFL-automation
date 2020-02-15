import threading
import time
import datetime
import pyFAI

class ReduceDaemon(threading.Thread):
    def __init__(self,app,reduction_queue,integrator,results,npts=500):
        app.logger.info('Creating ReduceDaemon thread')

        threading.Thread.__init__(self,name='ReduceDaemon',daemon=True)
        self._stop = False
        self._app = app
        self.reduction_queue = reduction_queue

        self.npts=npts
        self.integrator = integrator
    def terminate(self):
        self._app.logger.info('Terminating DoorDaemon thread')
        self._stop = True


    def run(self):
        while not self._stop:
            data = self.reduction_queue.get(block=True,timeout=None) # wait here until a job appears in queue
            1dres = self.integrator.integrate1d(data[2],self.npts,method='csr_ocl',unit='q_A^-1')
            2dres = self.integrator.integrate2d(data[2],self.npts,method='csr_ocl'unit='q_A^-1')
            results.append((data[0],data[1],data[2],1dres,2dres))
            time.sleep(0.01)
        self._app.logger.info('ReduceDaemon runloop exiting')
