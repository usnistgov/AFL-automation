import time
from typing import Optional
from numbers import Number
from pathlib import Path

from tiled.client import from_uri

import numpy as np
import lazy_loader as lazy

# Neutron scattering and control system dependencies
pye = lazy.load("epics", require="AFL-automation[neutron-scattering]")
ISISCommandInterface = lazy.load("sans.command_interface.ISISCommandInterface", require="AFL-automation[neutron-scattering]")
# Alias to match original code
ici = ISISCommandInterface

# Mantid will be loaded as needed through the SimpleAPI
mantid_simpleapi = lazy.load("mantid.simpleapi", require="AFL-automation[neutron-scattering]")
# For functions previously imported with * from mantid.simpleapi
# We'll use mantid_simpleapi.FunctionName instead

# SAS data handling
Loader = lazy.load("sasdata.dataloader.loader.Loader", require="AFL-automation[sas-analysis]")

from AFL.automation.APIServer.Driver import Driver

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

PREFIX = "//isis/inst$"


class ISISLARMOR(Driver):
    # self.config dictionary
    # anything you may want to change at run time, pull from defaults.config
    # these defaults will need to be changed
    defaults = {}
    defaults['sample_thickness'] = 1

    defaults['reduced_data_dir'] = './'

    defaults['open_beam_trans_rn'] = -1
    defaults['empty_cell_scatt_rn'] = -1
    defaults['empty_cell_trans_rn'] = -1

    defaults['slow_wait_time'] = 2
    defaults['fast_wait_time'] = 1
    defaults['file_wait_time'] = 1
    
    defaults['cycle_path'] = "/NDXLARMOR/Instrument/data/cycle_24_2/"
    defaults['mask_file'] = '/NDXLARMOR/User/Masks/USER_Beaucage_242D_AFL_r86070.TOML'
    

    def __init__(self,name:str='ISISLARMOR',overrides=None):
        """ """
        self.app = None
        Driver.__init__(self,name=name,defaults=self.gather_defaults(),overrides=overrides)

        self.status_str = "New Server"

        
    def status(self):
        status=[]
        status.append(self.status_str)
        return status
        

    def getRunNumber(self):
        rn = pye.caget("IN:LARMOR:DAE:IRUNNUMBER")
        return rn

    def trans_mode(self):
        pye.caput("IN:LARMOR:MOT:MTR0602.VAL", 0.0)
        time.sleep(self.config['slow_wait_time'])
        # need to wait for motor move
        while pye.caget("IN:LARMOR:MOT:MTR0602.DMOV") != 1:
            time.sleep(self.config['fast_wait_time'])
        time.sleep(self.config['slow_wait_time'])


    def scatt_mode(self):
        pye.caput("IN:LARMOR:MOT:MTR0602.VAL", 200.0)
        time.sleep(self.config['slow_wait_time'])
        # need to wait for motor move
        while pye.caget("IN:LARMOR:MOT:MTR0602.DMOV") != 1:
            time.sleep(self.config['fast_wait_time'])
        time.sleep(self.config['slow_wait_time'])

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
            time.sleep(self.config['slow_wait_time'])

    def abortrun(self):
        pye.caput("IN:LARMOR:DAE:ABORTRUN", 1)
        
    def endrun(self):
        pye.caput("IN:LARMOR:DAE:ENDRUN", 1)

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
            time.sleep(self.config['fast_wait_time'])
        print(f"{frames} frames counted")

    def waitforuah(self,uamps:Number=50):
        print(f"Waiting for {uamps} uamps")
        ua = pye.caget("IN:LARMOR:DAE:GOODUAH")
        while ua < uamps:
            time.sleep(self.config['fast_wait_time'])
            ua = pye.caget("IN:LARMOR:DAE:GOODUAH")
        print(f"{uamps} amps counted")

    def waitfortime(self,sec:Number=60):
        print(f"Waiting for {sec} seconds")
        t=pye.caget("IN:LARMOR:DAE:GOODFRAMES")/10
        while t < sec:
            time.sleep(self.config['fast_wait_time'])
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
            
    def waitforfile(self, fpath, max_t=900):
        # TODO: Check that the file is not changing, not that is just exists
        self.status_str = f"Waiting for file {fpath} to be written..."
        start_time = time.time()
        while not fpath.exists():
            time.sleep(self.config['file_wait_time'])
            now = time.time()
            if now - start_time >= max_t:
                raise FileNotFoundError(f"The file {fpath} was not written within {max_t} seconds.")
        while not os.access(str(fpath),os.R_OK):
            time.sleep(self.config['file_wait_time'])
            now = time.time()
            if now - start_time >= max_t:
                raise FileNotFoundError(f"The file {fpath} was not readable within {max_t} seconds.")
        self.status_str = f"File {fpath} exists and is readable."

    def waitforSASfile(self, fpath, max_t=900):
        # TODO: Check that the file is not changing, not that is just exists
        self.status_str = f"Waiting for file {fpath} to be written..."
        start_time = time.time()
        while not fpath.exists():
            try:
                loader = Loader()
                sasdata = loader.load(str(filename.absolute()))
                break
            except:
                time.sleep(self.config['file_wait_time'])
                now = time.time()
                if now - start_time >= max_t:
                    raise FileNotFoundError(f"The file {fpath} was not written within {max_t} seconds.")
        self.status_str = f"SASFile {fpath} was loaded successfully."
                
    def waitforsetup(self):
        # if RUNSTATE is in Setup, begin the run
        self.status_str = "Waiting for the instrument to be in the SETUP state."
        while pye.caget("IN:LARMOR:DAE:RUNSTATE") != 1:
            time.sleep(self.config['slow_wait_time'])
            
    def waitformotormove(self, motor="0602"):
        """Monitor the motor motion of motors that are nearly instant. Defaults to the monitor motor if no motor number is sent."""
        while pye.caget(f"IN:LARMOR:MTR{motor}:ISMOVING") != 1:
            time.sleep(self.config['slow_wait_time'])

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
            exposure_trans: Number,
            expose_metric:str='frames',
            reduce_data: bool=True,
            measure_transmission: bool=True
    ):
        """
        expose_metric: `frames`, `uamps`, or `time` in seconds; controls wait time
        expose_dose: exposure metric in frames, uamps, or seconds
        """
        self.waitforsetup()
        sampleTRANS_rn = self.getRunNumber()
        sampleTRANS_fname = self.getFilename()
        self.setRunTitle(name+"_trans")
        self.status_str = f"Now measuring transmission for run number {sampleTRANS_rn}"
        self.trans_mode()
        self.beginrun()
        self.waitfor(exposure_trans,expose_metric=expose_metric)
        self.endrun()

        self.waitforsetup()
        sampleSANS_fname = self.getFilename()
        self.setRunTitle(name+"_sans")
        self.scatt_mode()
        sampleSANS_rn = self.getRunNumber()
        self.status_str = f"Now measuring scattering for run number {sampleSANS_rn}"
        self.beginrun()
        self.waitfor(exposure,expose_metric=expose_metric)
        self.endrun()

        if reduce_data:
            self.waitforfile(Path(PREFIX) / self.config['cycle_path'] / sampleSANS_fname)
            try:
                self.reduce(name=name, sampleSANS_rn=sampleSANS_rn, sampleTRANS_rn=sampleTRANS_rn,sample_thickness=self.config['sample_thickness'])
            except Exception as e:
                print(f'retrying reduction after an exception {e}, waiting 60 s first for any transient things to resolve')
                time.sleep(60)
                self.reduce(name=name, sampleSANS_rn=sampleSANS_rn, sampleTRANS_rn=sampleTRANS_rn,sample_thickness=self.config['sample_thickness'])
            return self.data['transmission']
    def reduce(self, sampleSANS_rn: int, sampleTRANS_rn: Optional[int]=None, sample_thickness: Number=2, name:str=""):
        prefix = "//isis/inst$"
        ConfigService.setDataSearchDirs(
            prefix + "/NDXLARMOR/User/Masks/;" + \
            prefix + self.config['cycle_path'])
        #mask_file = prefix + '/NDXLARMOR/User/Masks/USER_Beaucage_235C_SampleChanger_r80447.TOML'
        mask_file = prefix + self.config['mask_file']
        self.status_str = f"Reducing run number {sampleSANS_rn}."
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

        filename = Path(savedir) / (str(sampleSANS_rn) + f"_{name}_" + '_rear_1D_0.9_13.5.h5')
        self.status_str = f"Writing the reduced data for run number {sampleSANS_rn} to {filename}."
        SaveNXcanSAS(
            str(sampleSANS_rn) + '_rear_1D_0.9_13.5',
            str(filename.absolute()),
            RadiationSource='Spallation Neutron Source',
            Transmission=str(sampleSANS_rn) + '_trans_Sample_0.9_13.5',
            TransmissionCan=str(sampleSANS_rn) + '_trans_Can_0.9_13.5'
        )
        
        DeleteWorkspace(str(sampleSANS_rn)+'_trans_0.9_13.5')
        DeleteWorkspace('optimization')
        DeleteWorkspace('sans_interface_raw_data')
        DeleteWorkspace(str(sampleSANS_rn)+'_rear_1D_0.9_13.5')
        
        self.waitforSASfile(filename)
        
        # load data from disk and send to tiled
        loader = Loader()
        sasdata = loader.load(str(filename.absolute()))
        if len(sasdata)>1:
            warnings.warn("Loaded multiple data from file...taking the last one",stacklevel=2)
            
        sasdata = sasdata[-1]
        self.data['transmission'] = np.mean(sasdata.trans_spectrum[-1].transmission)
        self.data['q'] = sasdata.x
        self.data['filename'] = filename
        self.data.add_array('q',sasdata.x)
        self.data.add_array('I',sasdata.y)
        self.data.add_array('dI',sasdata.dy)
        self.data.add_array('dq',sasdata.dx)
        
        self.data.add_array('transmission_spectrum',sasdata.trans_spectrum[-1].transmission)
        self.data.add_array('transmission_wavelength',sasdata.trans_spectrum[-1].wavelength)


if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
