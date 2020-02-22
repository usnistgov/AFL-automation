import queue
import threading
import time
import datetime
import pyFAI,pyFAI.azimuthalIntegrator
from CollateDaemon import CollateDaemon
from ReduceDaemon import ReduceDaemon
from PIL import Image
import numpy as np

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
    def __init__(self,app,results,debug_mode=True):
        app.logger.info('Creating EpicsADLiveProcessDaemon thread')

        threading.Thread.__init__(self,name='EpicsADLiveProcessDaemon',daemon=True)

        self.reduction_queue = queue.Queue()
        self.detector = pyFAI.detector_factory(name="pilatus300k")
        self.mask = np.array(Image.open('static/PIL5mask.tif'))
        self.integrator = pyFAI.azimuthalIntegrator.AzimuthalIntegrator(detector=self.detector,
                                                                        wavelength = 1.265e-10,
                                                                        dist = 2.435,
                                                                        poni1 = 0.0576,
                                                                        poni2 = 0.04120
                                                                        )

        self.collateDaemon = CollateDaemon(app,self.reduction_queue)
        self.collateDaemon.start()

        self.reduceDaemon = ReduceDaemon(app,self.reduction_queue,self.integrator,results,mask=self.mask)
        self.reduceDaemon.start()

        self._stop = False
        self._app = app
        self.results = results
        self.debug_mode = debug_mode

    def terminate(self):
        self.collateDaemon.terminate()
        self.reduceDaemon.terminate()

        self._app.logger.info('Terminating EADLPDaemon thread')
        self._stop = True
        self.task_queue.put(None)

    def run(self):
        while not self._stop:
            time.sleep(0.1)

        self._app.logger.info('EpicsADLiveProcessDaemon runloop exiting')

    







