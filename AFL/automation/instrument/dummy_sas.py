import gc
# import pythoncom
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
# from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument
# from AFL.automation.instrument.PySpecClient import PySpecClient
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL

# class DummySAS(ScatteringInstrument,Driver):
class DummySAS(Driver):
    defaults = {}
    def __init__(self,overrides=None):
        '''
        connect to spec

        '''

        self.app = None
        Driver.__init__(self,name='DummySAS',defaults=self.gather_defaults(),overrides=overrides)
        # ScatteringInstrument.__init__(self)


    @Driver.quickbar(qb={'button_text':'Expose',
        'params':{
        'exposure':{'label':'time (s)','type':'float','default':'5'},
        }})
    def expose(self,name=None,exposure=None,nexp=1,block=True,reduce_data=True,measure_transmission=True,save_nexus=True):
        time.sleep(exposure)
                
               
    def status(self):
        status = ['Dummy SAS Instrument']
        return status

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
