import threading
import time
import datetime
import pyFAI
import numpy as np

class ReduceDaemon(threading.Thread):
    def __init__(self,app,reduction_queue,integrator,results,mask=None,npts=500):
        app.logger.info('Creating ReduceDaemon thread')

        threading.Thread.__init__(self,name='ReduceDaemon',daemon=True)
        self._stop = False
        self._app = app
        self.reduction_queue = reduction_queue

        self.mask = mask

        self.npts=npts
        self.integrator = integrator
        self.results = results
    def terminate(self):
        self._app.logger.info('Terminating ReduceDaemon thread')
        self._stop = True


    def run(self):
        while not self._stop:
            if self.mask is None:
                mask = np.zeros(np.shape(data[2]))
            else:
                mask = self.mask

            data = self.reduction_queue.get(block=True,timeout=None) # wait here until a job appears in queue
            self._app.logger.info(f'Got {data[0]} from reduction queue, processing, ')
            res1d = self.integrator.integrate1d(data[2],self.npts,unit='q_A^-1',mask=mask,method='csr_ocl',error_model='azimuthal')
            res2d = self.integrator.integrate2d(data[2],self.npts,unit='q_A^-1',mask=mask,method='csr_ocl')
            self.results.append((data[0],data[1],data[2],res1d,res2d))
            time.sleep(0.001)
        self._app.logger.info('ReduceDaemon runloop exiting')
