import gc
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument
from AFL.automation.instrument.PySpecClient import PySpecClient
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL
import warnings
import json
import epics as pye

"""
Known PV names:
IN:LARMOR:DAE:GOODUAH - GOOD microamps, use this for accumulation of uamps as an exposure measure
IN:LARMOR:DAE:GOODFRAMES - GOOD Frames, 10 frames per sec if we want to use frames  for exposure time
IN:LARMOR:DAE:RUNSTATE - current run state
IN:LARMOR:DAE:BEGINRUN - begin run
IN:LARMOR:DAE:TITLE - title, use this to get the 
IN:LARMOR:DAE:TITLE:SP - title setpoint, use this to actually set the title
IN:LARMOR:DAE:IRUNNUMBER - run number
IN:LARMOR:DAE:INSTNAME - name of instance
IN:LARMOR:DAE:ABORTRUN - abort the run

*10 frames/sec can expose for time

Filename for reduced data should be [Title]_rear_1D_[lambdamin]_[lambdamax]
Filename for pre-reduced data should be as nxs file:
 LARMOR[RUN#] where [RUN#] is a (left) zero-padded run number
"""

class ISISLARMOR(ScatteringInstrument,Driver):
    # self.config dictionary
    # anything you may want to change at run time, pull from defaults.config
    # these defaults will need to be changed
    defaults = {}
    defaults['sample axis'] = 'Z-stage' # not X, do not move in the x-direction   
    defaults['sample_thickness'] = 1
    defaults['measurement_positions'] = 0
    
    def __init__(self,overrides=None):
        """
        connect to spec

        """

    def getRunNumber():
        rn = pye.caget("IN:LARMOR:DAE:IRUNNUMBER")
        return rn

    def beginrun():
        """
        RUNSTATE can be a number (1 to 14), important states are:
        1 - Setup
        2 - Running
        3 - Paused
        """
        rstate=pye.caget("IN:LARMOR:DAE:RUNSTATE")
        # if RUNSTATE is in Setup, begin the run
        if rstate == 1:
            pye.caput("IN:LARMOR:DAE:BEGINRUN", 1)
        # otherwise, 
        while rstate != 2:
            rstate=pye.caget("IN:LARMOR:DAE:RUNSTATE")
            time.sleep(2)
    def abortrun():
        pye.caput("IN:LARMOR:DAE:ABORTRUN", 1)

    def getRunTitle():
        title=pye.caget("IN:LARMOR:DAE:TITLE")
        stitle=""
        for i in title: 
            stitle+=chr(i)
        return stitle

    def setRunTitle(self, title):
        title = title.replace('\\','').replace('/','').replace(':','').replace('%','')
        pye.caput("IN:LARMOR:DAE:TITLE:SP", f"{title}"))

    def waitforframes(frames=5000):
        print(f"Waiting for {frames} frames"))
        frs=pye.caget("IN:LARMOR:DAE:GOODFRAMES")
        while frs < frames:
            frs=pye.caget("IN:LARMOR:DAE:GOODFRAMES")
        print(f"{frames} frames counted"

    def waitforuah(uamps=50):
        print(f"Waiting for {uamps} uamps")
        ua = pye.caget("IN:LARMOR:DAE:GOODUAH")
        while ua < uamps:
            ua = pye.caget("IN:LARMOR:DAE:GOODUAH")
        print(f"{amps} amps counted")

    def waitfortime(sec=60):
        print(f"Waiting for {sec} seconds"))
        t=pye.caget("IN:LARMOR:DAE:GOODFRAMES")/10
        while t < sec:
            t=pye.caget("IN:LARMOR:DAE:GOODFRAMES")/10
        print(f"{t} sec counted"

        
    @Driver.unqueued()
    def getFilename(self, type:[str]='raw', prefix:[str]="LARMOR", ext:[str]=None, lmin:[float]=None, lmax:[float]=None):
        """
        Filename for reduced data should be: [run#]_rear_1D_[lambdamin]_[lambdamax]
        Filename for pre-reduced data should be as nxs file: LARMOR[RUN#] where [RUN#] is a (left) zero-padded run number

        type
        """
        rn = self.getRunNumber()
        if type =='raw':
            if ext == None:
                ext = "nxs"
            fn = f'{prefix}{int(rn):08}.{ext}'
        else:
            title = self.getRunTitle()
            if ext == None:
                ext = "xml"
            fn = f"{title}_rear_1D_{lmin}_{lmax}.{ext}"
        return fn


    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def getData(self,**kwargs):
        """
        NOTE: THIS IS AN OLD DESCRIPTION AND FUNCTION NEEDS TO BE MADE
        Grabs raw data from the instrument using the last filepath
        converts it to a numpy array. If the file is not found this
        will retry 10 times with a 0.2 sec rest to allow the data
        to be actually registered by the instrument system post-expose
        """
        


    @Driver.quickbar(qb={'button_text':'Expose',
        'params':{
        'name':{'label':'Name','type':'text','default':'test_exposure'},
        'exposure':{'label':'Exposure (s)','type':'float','default':5},
        'reduce_data':{'label':'Reduce?','type':'bool','default':True},
        'measure_transmission':{'label':'Measure Trans?','type':'bool','default':True}
        }})
    def Expose(self, expose_metric:[str]='frames', expose_dose=50):
        """
        expose_metric: `frames`, `uamps`, or `time` in sconds; controls wait time
        expose_dose: exposure metric in frames, uamps, or seconds
        """
        self.beginrun()
        if expose_metric == 'frames':
            self.waitforframes(expose_dose)
        if expose_metric == 'uamps':
            self.waitforuah(expose_dose)
        if expose_metric == 'time':
            self.waitfortime(expose_dose)