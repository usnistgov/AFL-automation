import win32com
import win32com.client
from win32process import SetProcessWorkingSetSize
from win32api import GetCurrentProcessId,OpenProcess
from win32con import PROCESS_ALL_ACCESS
import gc
import pythoncom
import time
import datetime
from NistoRoboto.APIServer.driver.Driver import Driver
from NistoRoboto.instrument.ScatteringInstrument import ScatteringInstrument
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import scipy.ndimage as ndi


class CDSAXSLabview(ScatteringInstrument,Driver):
    defaults = {}
    defaults['beamstop axis'] = 'Beamstop-z'
    defaults['beamstop in'] = 12.5
    defaults['beamstop out'] = 3
    defaults['sample axis'] = 'Z-stage'
    defaults['sample in'] = 26.5
    defaults['sample out'] = 25.0
    defaults['use_new_motion_conventions'] = False
    defaults['nmc_beamstop_in'] = {'Beamstop-z':12.5}
    defaults['nmc_beamstop_out'] = {'Beamstop-z':3}
    defaults['nmc_sample_out'] = {'Z-stage':20.0,'X-stage':18.0}
    defaults['nmc_sample_in'] = {'Z-stage':26.5,'X-stage':0}
    defaults['empty transmission'] = None
    defaults['transmission strategy'] = 'sum'
    defaults['vi'] = 'C:\saxs_control\GIXD controls.vi'
    defaults['reduced_data_dir'] = r'Y:\\CDSAXS data\\autoreduce\\'
    defaults['absolute_pressure_limit']=1
    defaults['relative_pressure_ratio_limit']=10
    defaults['sample_thickness']=0.18 #cm
    defaults['absolute_calibration_factor']=1.0
    
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
        'Temperature': 11,
        'None': 12
    }
    
    axis_id_to_name_lut = {value:key for key, value in axis_name_to_id_lut.items()}
    
    def __init__(self,overrides=None):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''

        self.app = None
        Driver.__init__(self,name='CDSAXSLabview',defaults=self.gather_defaults(),overrides=overrides)
        ScatteringInstrument.__init__(self)
        
        if self.config['reduced_data_dir'] is not None:
            os.chdir(self.config['reduced_data_dir'])

        self.__instrument_name__ = 'NIST CDSAXS instrument'
        
        self.status_txt = 'Just started...'
        self.last_measured_transmission = [0,0,0,0]
        

    def pre_execute(self,**kwargs):
        pressure = self._getLabviewValue("Pressure (mbar)")
        #historical_pressure = self._getLabviewValue("Pressure Level Chart",lv=lv)
        print(f'Pressure: {pressure}')
        #print(f'Hist Press: {historical_pressure}')
        abs_trip = pressure > self.config['absolute_pressure_limit']
        #rel_trip = (pressure/historical_pressure.mean())>self.config['relative_pressure_ratio_limit']
        if abs_trip:# or rel_trip:
            #something has gone wrong -- vacuum excursion.  raise an exception so the queue pauses.
            raise Exception(f'Vacuum excursion!!  Trip reason {"abs_trip" if abs_trip else "rel_trip"} Current pressure is {pressure}')#, historical average{historical_pressure.mean()}.')

    def setReducedDataDir(self,path):
        self.config['reduced_data_dir'] = path
        os.chdir(path)

    def measureTransmission(self,exp=5,fn='trans',set_empty_transmission=False,return_full=False,update_beam_center=True,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            self.status_txt = 'Moving beamstop out for transmission...'
            self.moveAxis(self.config['nmc_beamstop_out'],block=True,lv=lv)
            self.moveAxis(self.config['nmc_sample_out'],block=True,lv=lv)
            self.status_txt = 'Measuring open beam intensity...'
            open_beam = self._simple_expose(exposure=exp,filename = 't-open-beam-'+fn,block=True,lv=lv)
            self.status_txt = 'Measuring sample direct beam intensity...'
            self.moveAxis(self.config['nmc_sample_in'],block=True)
            sample_transmission = self._simple_expose(exposure=exp,filename = 't-'+fn,block=True,lv=lv)
            self.status_txt = 'Moving beamstop back in...'
            self.moveAxis(self.config['nmc_beamstop_in'],lv=lv,block=True)
            self.status_txt = 'Processing transmission measurement...'
            trans = np.nan_to_num(sample_transmission).sum() / np.nan_to_num(open_beam).sum()
            self.app.logger.info(f'Measured raw transmission of {trans*100}%, with {np.nan_to_num(sample_transmission).sum()} counts on samp and {np.nan_to_num(open_beam).sum()} in open beam.')
            if set_empty_transmission:
                #XXX! Should this be stored in config?
                self.config['empty transmission'] = trans
                 
                retval = (trans,np.nan_to_num(open_beam).sum(),np.nan_to_num(sample_transmission).sum(),self.config['empty transmission'])
            elif self.config['empty transmission'] is not None:
                if return_full:
                    # sample transmission, open flux, sample flux, empty transmission      
                    retval = (trans / self.config['empty transmission'],np.nan_to_num(open_beam).sum(),np.nan_to_num(sample_transmission).sum(),self.config['empty transmission'])
                else:
                    retval = trans / self.config['empty transmission']
                self.app.logger.info(f'Scaling raw transmission of {trans*100}% using empty transmission of {self.config["empty transmission"]*100} % for reported sample transmission of {trans / self.config["empty transmission"]*100}%')
            else:
                if return_full:
                    retval=(trans,np.nan_to_num(open_beam).sum(),np.nan_to_num(sample_transmission).sum())
                else:
                    retval = trans
            
            com = ndi.center_of_mass(np.nan_to_num(open_beam))
            print(f'Fit center of mass {com} in open beam')
            print(f'That converts to poni1 = {1.72e-4*com[0]} and poni2 = {1.72e-4*com[1]}')
            print(f'poni1 should be {self.config["poni1"]} and poni2 {self.config["poni2"]}')
            if update_beam_center:
                self.config['poni1'] = 1.72e-4*com[0]
                self.config['poni2'] = 1.72e-4*com[1]
            self.last_measured_transmission = retval
            self.status_txt = 'Idle'
            return retval
    
    def measureTransmissionQuick(self,exp=1,fn='trans',setup=False,restore=False,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            if setup:
                self.moveAxis(self.config['nmc_beamstop_out'],block=True,lv=lv)
                self.moveAxis(self.config['nmc_sample_out'],block=True,lv=lv)
                open_beam = self._simple_expose(exposure=exp,filename = 't-open-beam-'+fn,block=True,lv=lv)
                self.config['open beam intensity'] = np.nan_to_num(open_beam).sum()
                #self.config['open beam intensity updated'] = datetime.datetime.now()
                
                self.moveAxis(self.config['nmc_sample_in'],block=True,lv=lv)
                self.status_txt = 'Staged for rapid transmission measurement'
            sample_transmission = self._simple_expose(exposure=exp,filename = 't-'+fn,block=True,lv=lv)
            retval = np.nan_to_num(sample_transmission).sum()
            if self.config['open beam intensity'] is not None:
                retval = retval / self.config['open beam intensity']
            if restore:
                self.moveAxis(self.config['nmc_beamstop_in'],lv=lv,block=True)
                self.status_txt = 'Idle'
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

        name = name.replace('\\','').replace('/','').replace(':','').replace('%','')
            
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
        return self._getLabviewValue('Process Status Message',lv=lv)
   
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
    
#    def moveAxis(self,axis,value,exposure=0.001,filename = 'axis-move',return_data=False,block=True,lv=None):
#        #this is very hacky, I apologize.  The strategy is simply to set a sweep and do an exposure.  This is because of  labview-COM issue where we can't click the 'move axis' button.
#        
#        with (LabviewConnection() if lv is None else lv) as lv:
#            self.setSweepAxis(axis,lv=lv)
#            self.setSweepStart(value,lv=lv)
#            self.setExposure(exposure,lv=lv)
#            self.setFilename(filename,lv=lv)
#            self.setNScans(1,lv=lv)
#            self._setLabviewValue('Expose Pilatus',True,lv=lv)
#            if block or return_data:
#                while(self.getStatus(lv=lv) != 'Loading Image'):
#                    time.sleep(0.1)
#                while(self.getStatus(lv=lv) != 'Success' and self.getStatus(lv=lv) != 'Collection Aborted'):
#                    time.sleep(0.1)
#            if return_data:
#                return self.getData(lv=lv)
    def __moveAxis(self,axis,value,block=True,lv=None):
        '''
        Moves a single axis using a connection to a labview vi.
        @param axis: the axis id or name of the motor to move
        @param value: the position of the motor to move to
        @param block: if True, this function will not return until the move is complete.
        @param lv: a LabviewConnection object for use in integration with broader functions.  If None (default) will make a new connection.
        '''
        with LabviewConnection(vi=r'C:\saxs_control\Move for Peter.vi') as lvm:
            if type(axis) is str:
                axis = self.axis_name_to_id_lut[axis]#this converts the axis name to an ID number used by labview
            lvm.main_vi.setcontrolvalue('Axis',axis) #set the ‘axis’ drop-down box to the right axis
            lvm.main_vi.setcontrolvalue('New Position',value) # type the position into the destination position box
            lvm.main_vi.setcontrolvalue('Motor Move',True) # click the motor move button
            
            if block:
                with (LabviewConnection() if lv is None else lv) as lv: # this makes a connection to the main vi or uses an existing one if passed in
                    while('Moving' not in self.getStatus(lv=lv)): # wait for the instrument status to actually go to ‘moving’
                        time.sleep(0.1) #this just keeps the traffic down on the labview interface by only checking every 100 ms
                    while(self.getStatus(lv=lv) != 'Finished'): # wait for the instrument status to change to ‘finished’
                        time.sleep(0.1)
    def moveAxis(*args,block=True,lv=None):
        self=args[0]
        if len(args)==2:
            self.nmcMoveAxis(args[1],block=block,lv=lv)
        else:
            self.__moveAxis(args[1],args[2],block=block,lv=lv)
            
    def nmcMoveAxis(self,dest,block=True,lv=None):
        for motor,pos in dest.items():
            self.__moveAxis(motor,pos,block=block,lv=None)
            
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

    @Driver.unqueued()  
    def getElapsedTime(self,lv=None):
        return self._getLabviewValue('Elapsed Time',lv=lv)

    def _getLabviewValue(self,val_name,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            return lv.main_vi.getcontrolvalue(val_name)


    def _setLabviewValue(self,val_name,val_val,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            lv.main_vi.setcontrolvalue(val_name,val_val)

    def _simple_expose(self,filename=None,exposure=None,block=True,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            if filename is None:
                filename=self.getFilename(lv=lv)

            if exposure is None:
                exposure=self.getExposure(lv=lv)
            
            self.status_txt = f'Starting {exposure} s count named {filename}'
            
            self.setFilename(filename,lv=lv)
            self.setExposure(exposure,lv=lv)
            self.setNScans(1,lv=lv)
            self.setSweepAxis('None',lv=lv)
            
                
            if self.app is not None:
                self.app.logger.debug(f'Starting exposure with name {filename} for {exposure} s')


            self._setLabviewValue('Expose Pilatus',True,lv=lv)
            #time.sleep(0.5)
            if block:
                while(self.getStatus(lv=lv) != 'Loading Image'):
                    time.sleep(0.1)
                #name = self._getLabviewValue('Displayed Image P') # read back the actual name, including sequence number, for later steps.
                while(self.getStatus(lv=lv) != 'Success' and self.getStatus(lv=lv) != 'Collection Aborted'):
                    time.sleep(0.1)
                self.status_txt = 'Accessing Image'
                return self.getData(lv=lv)

    def expose(self,name=None,exposure=None,block=True,reduce_data=True,measure_transmission=True,save_nexus=True,sample_position=None,sample_thickness=None,lv=None):
        with (LabviewConnection() if lv is None else lv) as lv:
            if name is None:
                name=self.getFilename(lv=lv)

            if exposure is None:
                exposure=self.getExposure(lv=lv)
            
            if sample_position is not None:
                cached_pos = self.config['nmc_sample_in']
                self.config['nmc_sample_in'] = sample_position

            if sample_thickness is not None:
                cached_thickness = self.config['sample_thickness']
                self.config['sample_thickness'] = sample_thickness
            
            self.status_txt = f'Starting {exposure} s count named {name}'
            
            if measure_transmission:
                self.status_txt = f'Measuring transmission...'
                transmission = self.measureTransmission(return_full=True,lv=lv)
                self.status_txt = f'Starting {exposure} s count named {name} with transmission {str(transmission)}'
            else:
                transmission = [1,1,1,1]
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
                self.status_txt = 'Accessing Image'
                data = self.getData(lv=lv)
                if save_nexus:
                    self.status_txt = 'Writing Nexus'
                    self._writeNexus(data,name,name,transmission)
                if reduce_data:
                    self.status_txt = 'Reducing Data'
                    reduced = self.getReducedData(write_data=True,filename=name,filename_kwargs={'lv':lv})
                    #if save_nexus:
                        #self._appendReducedToNexus(reduced,name,name)
            self.status_txt = 'Instrument Idle'
            if sample_position is not None:
                self.config['nmc_sample_in'] = cached_pos
            if sample_thickness is not None:
                self.config['sample_thickness'] = cached_thickness
            
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
                
               
    def status(self):
        status = []
        status.append(f'Last Measured Transmission: scaled={self.last_measured_transmission[0]} using empty cell trans of {self.last_measured_transmission[3]} with {self.last_measured_transmission[2:3]} raw counts in open/sample')
        status.append(f'Status: {self.status_txt}')
        #lmj = self._getLabviewValue("LMJ Status")
        
        #status.append(f'LMJ status: {"running, power on target = "+str(lmj[0]*lmj[1])+"W" if lmj[6]==1 else "not running"}')
        #status.append(f'Vacuum (mbar): {self._getLabviewValue("Pressure (mbar)")}')
        status.append(f'<a href="getData" target="_blank">Live Data (2D)</a>')
        status.append(f'<a href="getReducedData" target="_blank">Live Data (1D)</a>')
        status.append(f'<a href="getReducedData?render_hint=2d_img&reduce_type=2d">Live Data (2D, reduced)</a>')
        return status
class LabviewConnection():

    def __init__(self,vi=r'C:\saxs_control\GIXD controls.vi'):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''
        #print(f'init labview context...')
        self.vi = vi
        #print(f'Entering Labview context...')
        pythoncom.CoInitialize()
        self.labview = win32com.client.dynamic.Dispatch("Labview.Application")
        self.main_vi = self.labview.getvireference(self.vi)
        #self.main_vi.setcontrolvalue('Measurement',3) # 3 should bring the single Pilatus tab to the front

    def __enter__(self):
        
        return self

    def __exit__(self,exittype,value,traceback):
        pass #print(f'Exiting LabView context...')
        
    def __del__(self):
        #print(f'Deleting Labview object...')
        self.main_vi = None
        self.labview = None
        gc.collect()
        pythoncom.CoUninitialize()
        if(pythoncom._GetInterfaceCount()>0):
            print(f'Closed COM connection, but had remaining objects: {pythoncom._GetInterfaceCount()}')
            SetProcessWorkingSetSize(OpenProcess(PROCESS_ALL_ACCESS,True,GetCurrentProcessId()),-1,-1)
