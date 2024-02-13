import time
from typing import Optional
from numbers import Number

from tiled.client import from_uri

import epics as pye
import sans.command_interface.ISISCommandInterface as ici
# import mantid algorithms, numpy and matplotlib
from mantid.simpleapi import *

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument

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

    defaults['reduced_data_dir'] = './'
    defaults['tiled_uri'] = './'

    defaults['open_beam_trans_rn'] = -1
    defaults['empty_cell_scatt_rn'] = -1
    defaults['empty_cell_trans_rn'] = -1

    def __init__(self,name:str='ISISLARMOR',overrides=None):
        """ """
        self.app = None
        Driver.__init__(self,name=name,defaults=self.gather_defaults(),overrides=overrides)
        ScatteringInstrument.__init__(self)

        self.tiled_client = from_uri(self.config['tiled_uri'],api_key='NistoRoboto642')

    def getRunNumber(self):
        rn = pye.caget("IN:LARMOR:DAE:IRUNNUMBER")
        return rn

    def trans_mode(self):
        pye.caput("IN:LARMOR:MOT:MTR0602.VAL", 0.0)
        time.sleep(15)

    def scatt_mode(self):
        pye.caput("IN:LARMOR:MOT:MTR0602.VAL", 200.0)
        time.sleep(15)

    def beginrun(self):
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

    def abortrun(self):
        pye.caput("IN:LARMOR:DAE:ABORTRUN", 1)

    def getRunTitle(self):
        title=pye.caget("IN:LARMOR:DAE:TITLE")
        stitle=""
        for i in title: 
            stitle+=chr(i)
        return stitle

    def setRunTitle(self, title: str):
        title = title.replace('\\','').replace('/','').replace(':','').replace('%','')
        pye.caput("IN:LARMOR:DAE:TITLE:SP", f"{title}")

    def waitforframes(self,frames:Number=5000):
        print(f"Waiting for {frames} frames")
        frs=pye.caget("IN:LARMOR:DAE:GOODFRAMES")
        while frs < frames:
            frs=pye.caget("IN:LARMOR:DAE:GOODFRAMES")
        print(f"{frames} frames counted")

    def waitforuah(self,uamps:Number=50):
        print(f"Waiting for {uamps} uamps")
        ua = pye.caget("IN:LARMOR:DAE:GOODUAH")
        while ua < uamps:
            ua = pye.caget("IN:LARMOR:DAE:GOODUAH")
        print(f"{uamps} amps counted")

    def waitfortime(self,sec:Number=60):
        print(f"Waiting for {sec} seconds")
        t=pye.caget("IN:LARMOR:DAE:GOODFRAMES")/10
        while t < sec:
            t=pye.caget("IN:LARMOR:DAE:GOODFRAMES")/10
        print(f"{t} sec counted")

    def waitfor(self, exposure: Number, expose_metric:str):
        self.beginrun()
        if expose_metric == 'frames':
            self.waitforframes(exposure)
        elif expose_metric == 'uamps':
            self.waitforuah(exposure)
        elif expose_metric == 'time':
            self.waitfortime(exposure)
        else:
            raise ValueError(f'Invalid exposure metric = {expose_metric}')

    def getFilename(self, type:str='raw', prefix:str="LARMOR", ext:str=None, lmin:float=None, lmax:float=None):
        """
        Filename for reduced data should be: [run#]_rear_1D_[lambdamin]_[lambdamax]
        Filename for pre-reduced data should be as nxs file: LARMOR[RUN#] where [RUN#] is a (left) zero-padded run number
        """
        rn = self.getRunNumber()
        if type =='raw':
            if ext is None:
                ext = "nxs"
            fn = f'{prefix}{int(rn):08}.{ext}'
        else:
            title = self.getRunTitle()
            if ext is None:
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
    def expose(
            self,
            name: str,
            exposure: Number,
            empty_exposure: Number,
            expose_metric:str='frames',
            reduce_data: bool=True,
            measure_transmission: bool=True
    ):
        """
        expose_metric: `frames`, `uamps`, or `time` in sconds; controls wait time
        expose_dose: exposure metric in frames, uamps, or seconds
        """
        self.setRunTitle(name+"_trans")
        self.trans_mode()
        self.beginrun()
        self.waitfor(empty_exposure)
        self.abortrun()
        sampleTRANS_rn = self.getRunNumber()

        self.setRunTitle(name+"_sans")
        self.scatt_mode()
        self.beginrun()
        self.waitfor(exposure)
        self.abortrun()
        sampleSANS_rn = self.getRunNumber()

        if reduce_data:
            self.reduce(name=name, sampleSANS_rn=sampleSANS_rn, sampleTRANS_rn=sampleTRANS_rn)
    def reduce(self, sampleSANS_rn: int, sampleTRANS_rn: Optional[int]=None, sample_thickness: Number=1, name:str=""):
        prefix = "//isis/inst$"
        ConfigService.setDataSearchDirs(
            prefix + "/NDXLARMOR/User/Masks/;" + \
            prefix + "/NDXLARMOR/Instrument/data/cycle_23_5/")
        mask_file = prefix + '/NDXLARMOR/User/Masks/USER_Beaucage_235C_SampleChanger_r80447.TOML'

        ici.Clean()
        ici.LARMOR()
        ici.Set1D()

        ici.MaskFile(mask_file)

        DBTRANS = self.config['open_beam_trans_rn']
        canSANS = self.config['empty_cell_scatt_rn']
        canTRANS = self.config['empty_cell_trans_rn']

        savedir = self.config['reduced_data_dir']

        ici.AssignSample(str(sampleSANS_rn))
        ici.AssignCan(str(canSANS))
        ici.TransmissionSample(str(sampleTRANS_rn), str(DBTRANS))
        ici.TransmissionCan(str(canTRANS), str(DBTRANS))

        ici.WavRangeReduction(None, None)
        # SaveCanSAS1D(str(sampleSANS_rn) + '_rear_1D_0.9_13.5', savedir + str(sampleSANS_rn) + '_rear_1D_0.9_13.5.xml', \
        #              Geometry='Flat plate', SampleHeight='8', SampleWidth='6', SampleThickness=sample_thickness, \
        #              Append=False, Transmission=str(sampleSANS_rn) + '_trans_Sample_0.9_13.5',
        #              TransmissionCan=str(sampleSANS_rn) + '_trans_Can_0.9_13.5')

        filename = savedir + str(sampleSANS_rn) + f"_{name}_" + '_rear_1D_0.9_13.5.h5'
        SaveNXcanSAS(
            str(sampleSANS_rn) + f"_{name}_" + '_rear_1D_0.9_13.5',
            filename,
            RadiationSource='Spallation Neutron Source',
            Transmission=str(sampleSANS_rn) + '_trans_Sample_0.9_13.5',
            TransmissionCan=str(sampleSANS_rn) + '_trans_Can_0.9_13.5',
            SampleThickness=sample_thickness
        )



