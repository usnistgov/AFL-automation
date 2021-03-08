import win32com
import win32com.client
import pythoncom
import time
from NistoRoboto.APIServer.driver.Driver import Driver
from NistoRoboto.instrument.ScatteringInstrument import ScatteringInstrument
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os


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
    
    def __init__(self,vi=r'C:\saxs_control\GIXD controls.vi',reduced_data_dir=None,**kwargs):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''

        self.app = None
        self.name = 'CDSAXSLabview'
        
        super().__init__(**kwargs)
        
        self.setReductionParams({'poni1':0.0251146,'poni2':0.150719,'rot1':0,'rot2':0,'rot3':0,'wavelength':1.3421e-10,'dist':3.4925,'npts':500})
        self.setMaskPath(r'Y:\Peter automation software\CDSAXS_mask_20210306.edf')
        if reduced_data_dir is not None:
            os.chdir(reduced_data_dir)
        self.config = {}
        self.config['beamstop axis'] = 'Beamstop-z'
        self.config['beamstop in'] = 12.5
        self.config['beamstop out'] = 3
        self.config['sample axis'] = 'Z-stage'
        self.config['sample in'] = 26.5
        self.config['sample out'] = 25.0
        self.config['empty transmission'] = None
        self.config['transmission strategy'] = 'sum'
        
        self.__instrument_name__ = 'NIST CDSAXS instrument'
        
        

    def measureTransmission(self,exp=5,fn='trans',set_empty_transmission=False,return_full=False,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            self.moveAxis(self.config['beamstop axis'],self.config['beamstop out'],lv=lv)
            open_beam = self.moveAxis(self.config['sample axis'],self.config['sample out'],exposure=exp,filename = 't-open-beam-'+fn,return_data=True,lv=lv)
            sample_transmission = self.moveAxis(self.config['sample axis'],self.config['sample in'],exposure=exp,filename = 't-'+fn,return_data=True,lv=lv)
            self.moveAxis(self.config['beamstop axis'],self.config['beamstop in'],lv=lv,block=True)
            trans = np.nan_to_num(sample_transmission).sum() / np.nan_to_num(open_beam).sum()
            self.app.logger.info(f'Measured raw transmission of {trans*100}%, with {np.nan_to_num(sample_transmission).sum()} counts on samp and {np.nan_to_num(open_beam).sum()} in open beam.')
            if set_empty_transmission:
                self.config['empty transmission'] = trans
                retval = 'Done'
            elif self.config['empty transmission'] is not None:
                if return_full:
                    retval = (trans / self.config['empty transmission'],np.nan_to_num(open_beam).sum(),np.nan_to_num(sample_transmission).sum(),self.config['empty transmission'])
                else:
                    retval = trans / self.config['empty transmission']
                self.app.logger.info(f'Scaling raw transmission of {trans*100}% using empty transmission of {self.config["empty transmission"]*100} % for reported sample transmission of {trans / self.config["empty transmission"]*100}%')
            else:
                if return_full:
                    retval=(trans,np.nan_to_num(open_beam).sum(),np.nan_to_num(sample_transmission).sum())
                else:
                    retval = trans
            return retval
    
    def measureTransmissionQuick(self,exp=1,fn='trans',setup=False,restore=False,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            if setup:
                self.moveAxis(self.config['beamstop axis'],self.config['beamstop out'],lv=lv)
                open_beam = self.moveAxis(self.config['sample axis'],self.config['sample out'],exposure=exp,filename = 't-open-beam-'+fn,return_data=True,lv=lv)
                self.config['open beam intensity'] = np.nan_to_num(open_beam).sum()
                self.config['open beam intensity updated'] = datetime.datetime.now()
            sample_transmission = self.moveAxis(self.config['sample axis'],self.config['sample in'],exposure=exp,filename = 't-'+fn,return_data=True,lv=lv)
            retval = np.nan_to_num(sample_transmission).sum()
            if self.config['open beam intensity'] is not None:
                retval = retval / self.config['open beam intensity']
            if restore:
                self.moveAxis(self.config['beamstop axis'],self.config['beamstop in'],lv=lv,block=True)
            return retval          


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

        name = name.replace('\\','').replace('/','').replace(':','')
            
        exposure = self.getExposure()

        self._setLabviewValue('Single Pilatus Parameters',(exposure,name),lv=lv)

    
    @Driver.unqueued(render_hint='2d_img',log_image=True,lv=None)
    def getData(self,lv=None,**kwargs):
        data = np.array(self._getLabviewValue('Pilatus Data',lv=lv))
        return data

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
        
    def setNScans(self,nscans,lv=None):
        self._setLabviewValue('# of Scans',nscans,lv=lv)
    
    @Driver.unqueued()  
    def getSweepAxis(self,lv=None):
        return self.axis_id_to_name_lut[self._getLabviewValue('Sweep Axis',lv=lv)]

    def setSweepAxis(self,axis,lv=None):
        print(f'setting sweep axis to {axis}')
        if type(axis) is str:
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
    
    def moveAxis(self,axis,value,exposure=0.001,filename = 'axis-move',return_data=False,block=True,lv=None):
        #this is very hacky, I apologize.  The strategy is simply to set a sweep and do an exposure.  This is because of  labview-COM issue where we can't click the 'move axis' button.
        
        with (LabviewConnection() if lv is None else lv) as lv:
            self.setSweepAxis(axis,lv=lv)
            self.setSweepStart(value,lv=lv)
            self.setExposure(exposure,lv=lv)
            self.setFilename(filename,lv=lv)
            self.setNScans(1,lv=lv)
            self._setLabviewValue('Expose Pilatus',True,lv=lv)
            if block or return_data:
                while(self.getStatus(lv=lv) != 'Loading Image'):
                    time.sleep(0.1)
                while(self.getStatus(lv=lv) != 'Success' and self.getStatus(lv=lv) != 'Collection Aborted'):
                    time.sleep(0.1)
            if return_data:
                return self.getData(lv=lv)
        
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
        with (LabviewConnection() if lv is None else lv) as lv:
            return lv.main_vi.getcontrolvalue(val_name)


    def _setLabviewValue(self,val_name,val_val,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            lv.main_vi.setcontrolvalue(val_name,val_val)



    def expose(self,name=None,exposure=None,block=True,reduce_data=True,measure_transmission=True,save_nexus=True,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            if name is None:
                name=self.getFilename(lv=lv)

            if exposure is None:
                exposure=self.getExposure(lv=lv)

            if measure_transmission:
                transmission = self.measureTransmission(return_full=True,lv=lv)
                
            self.setFilename(name,lv=lv)
            self.setExposure(exposure,lv=lv)
            self.setNScans(1,lv=lv)
            self.setSweepAxis('None',lv=lv)
            
                
            if self.app is not None:
                self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')


            self._setLabviewValue('Expose Pilatus',True,lv=lv)
            #time.sleep(0.5)
            if block or reduce_data or save_nexus:
                while(self.getStatus(lv=lv) != 'Loading Image'):
                    time.sleep(0.1)
                #name = self._getLabviewValue('Displayed Image P') # read back the actual name, including sequence number, for later steps.
                while(self.getStatus(lv=lv) != 'Success' and self.getStatus(lv=lv) != 'Collection Aborted'):
                    time.sleep(0.1)
                data = self.getData()
                if save_nexus:
                    self._writeNexus(data,name,name,transmission)
                if reduce_data:
                    reduced = self.getReducedData(write_data=True,filename=name,filename_kwargs={'lv':lv})
                    #if save_nexus:
                        #self._appendReducedToNexus(reduced,name,name)
                
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
        #self.main_vi.setcontrolvalue('Measurement',3) # 3 should bring the single Pilatus tab to the front
        return self

    def __exit__(self,exittype,value,traceback):
        self.labview=None
        self.main_vi=None
        pythoncom.CoUninitialize()
        