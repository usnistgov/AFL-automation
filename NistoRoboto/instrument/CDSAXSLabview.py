import win32com
import win32com.client
import pythoncom
import time
from NistoRoboto.APIServer.driver.Driver import Driver
from NistoRoboto.instrument.ScatteringInstrument import ScatteringInstrument
import numpy as np # for return types in get data


class CDSAXSLabview(ScatteringInstrument,Driver):
    
    axis_name_to_id_lut = {
        'X-stage' : 0,
        'Z-stage' : 1,
        'Z-gonio' : 2,
        'Phi' : 3,
        'Theta' : 4,
        'Y-gonio' : 5,
        'Y-stage' : 6,
        'Beamstop-z': 7,
        'Beamstop-y': 8,
        'Tungsten-y': 9 ,
        'Detector-z': 10,
        'None': 11
    }
    
    axis_id_to_name_lut = {value:key for key, value in axis_name_to_id_lut.items()}
    
    def __init__(self,vi=r'C:\saxs_control\GIXD controls.vi',**kwargs):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''

        self.app = None
        self.name = 'CDSAXSLabview'
        
        super().__init__(**kwargs)
        
        self.setReductionParams({'poni1':0.0246703,'poni2':0.1495366,'rot1':0,'rot2':0,'rot3':0,'wavelength':1.3421e-10,'dist':3.484,'npts':500})
        self.setMaskPath(r'Y:\Peter automation software\CDSAXS_mask_20210225_2.edf')


    @Driver.unqueued()        
    def getExposure(self,lv=None):
        '''
            get the currently set exposure time

        '''
        return self._getLabviewValue('Single Pilatus Parameters',lv=lv)[0]

        
    @Driver.unqueued()
    def getFilename(self,lv=None):
        '''
            get the currently set file name

        '''
        return self._getLabviewValue('Single Pilatus Parameters',lv=lv)[1]

   
    def setExposure(self,exposure,lv=None):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
                
        fileName = self.getFilename(lv=lv)

        self._setLabviewValue('Single Pilatus Parameters',(exposure,fileName),lv=lv)

    def setFilename(self,name,lv=None):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        if '\\' in name:
            raise ValueError('cannot have slashes in filename')
            
        exposure = self.getExposure()

        self._setLabviewValue('Single Pilatus Parameters',(exposure,name),lv=lv)

    
    @Driver.unqueued(render_hint='2d_img',log_image=True,lv=None)
    def getData(self,lv=None,**kwargs):
        data = np.array(self._getLabviewValue('Pilatus Data',lv=lv))

    def setPath(self,path,lv=None):
        if self.app is not None:
            self.app.logger.debug(f'Setting file path to {path}')

        self.path = str(path)
        self._setLabviewValue('FilePath',path,lv=lv)
        
    @Driver.unqueued()  
    def getStatus(self,lv=None):
        return self._getLabviewValue('Process Status Message')
   
    @Driver.unqueued()  
    def getNScans(self,lv=None):
        return self._getLabviewValue('# of Scans',lv=lv)
        
    def setNScans(self,nscans,lv=lv):
        self._setLabviewValue('# of Scans',nscans,lv=lv)
    
    @Driver.unqueued()  
    def getSweepAxis(self,lv=None):
        return self.axis_id_to_name_lut[self._getLabviewValue('Sweep Axis',lv=lv)]

    def setSweepAxis(self,axis,lv=None):
        if type(axis)=='str':
            axis=self.axis_name_to_id_lut[axis]
        self._setLabviewValue('Sweep Axis',axis,lv=lv) # this is an enum, 6 is Y-stage
    
    @Driver.unqueued()  
    def getYStagePos(self,lv=None):
        return self._getLabviewValue('Y-stage',lv=lv)
    @Driver.unqueued()  
    def getZStagePos(self,lv=None):
        return self._getLabviewValue('Z-stage',lv=lv)
    @Driver.unqueued()  
    def getXStagePos(self,lv=None):
        return self._getLabviewValue('X-Stage',lv=lv)
    
    
    def setSweepStart(self,start,lv=None):
        self._setLabviewValue('Start Value',start,lv=lv)
        
    @Driver.unqueued()  
    def getSweepStart(self,lv=None):
        return self._getLabviewValue('Start Value',lv=lv)
    
    def setSweepStep(self,step,lv=None):
        self._setLabviewValue('Step',step,lv=lv)
    
    @Driver.unqueued()  
    def getSweepStep(self,lv=None):
        return self._getLabviewValue('Step',lv=lv)


    def _getLabviewValue(self,val_name,lv=None):
        if lv is None:
            with LabviewConnection() as lv:
                ret_val = lv.main_vi.getcontrolvalue(val_name)
        else:
            ret_val = lv.main_vi.getcontrolvalue(val_name)
        return ret_val

    def _setLabviewValue(self,val_name,val_val,lv=None):
        if lv is None:
            with LabviewConnection() as lv:
                lv.main_vi.setcontrolvalue(val_name,val_val)
        else:
            lv.main_vi.setcontrolvalue(val_name,val_val)


    def expose(self,name=None,exposure=None,block=True,reduce_data=True):
        with LabviewConnection() as lv:

            if name is not None:
                self.setFilename(name,lv=lv)
            else:
                name=self.getFilename(lv=lv)

            if exposure is not None:
                self.setExposure(exposure,lv=lv)
            else:
                exposure=self.getExposure(lv=lv)

            self.setNScans(1,lv=lv)
            self.setSweepAxis('None',lv=lv)
            
                
            if self.app is not None:
                self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')


            self._setLabviewValue('Expose Pilatus',True,lv=lv)
            time.sleep(0.5)
            if block or reduce_data:
                while(self.getStatus(lv=lv) != 'Success'):
                    time.sleep(0.1)

                if reduce_data:
                    self.getReducedData(write_data=True,filename_kwargs={'lv':lv})

                
    def scan(self,axis,npts,start,step,name=None,exposure=None,block=False):
        if name is not None:
            self.setFilename(name)
        else:
            name=self.getFilename()

        if exposure is not None:
            self.setExposure(exposure)
        else:
            exposure=self.getExposure()

        self.setNScans(npts)
        self.setSweepAxis(axis)
        self.setSweepStart(start)
        self.setSweepStep(step)
            
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')

        with LabviewConnection() as lv:
            lv.main_vi.setcontrolvalue('Expose Pilatus',True)
        time.sleep(0.5)
        if block:
            while(self.getStatus() != 'Success'):
                time.sleep(0.1)

class LabviewConnection():

    def __init__(self,vi=r'C:\saxs_control\GIXD controls.vi'):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''

        self.vi = vi
        

    def __enter__(self):
        pythoncom.CoInitialize()
        self.labview = win32com.client.dynamic.Dispatch("Labview.Application")
        self.main_vi = self.labview.getvireference(self.vi)
        self.main_vi.setcontrolvalue('Measurement',3) # 3 should bring the single Pilatus tab to the front
        return self

    def __exit__(self,exittype,value,traceback):
        self.labview=None
        self.main_vi=None
        pythoncom.CoUninitialize()
        