# import win32com
# import win32com.client
# from win32process import SetProcessWorkingSetSize
# from win32api import GetCurrentProcessId,OpenProcess
# from win32con import PROCESS_ALL_ACCESS
import gc
# import pythoncom
import time
import datetime
from NistoRoboto.APIServer.driver.Driver import Driver
from NistoRoboto.instrument.ScatteringInstrument import ScatteringInstrument
from NistoRoboto.instrument.PySpecClient import PySpecClient
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL

class CHESSID3B(ScatteringInstrument,Driver):
    defaults = {}
    defaults['sample axis'] = 'Z-stage'
    defaults['sample in'] = 26.5
    defaults['sample out'] = 25.0
    defaults['empty transmission'] = None
    defaults['transmission strategy'] = 'sum'
    defaults['reduced_data_dir'] = '/mnt/home/chess_id3b/beaucage/211012-data'
    defaults['exposure'] = 1.
    defaults['i0_counter'] = 'ic3'
    defaults['diode_counter'] = 'diode'
    defaults['preferred_det'] = 'PIL5'    
    def __init__(self,overrides=None):
        '''
        connect to spec

        '''

        self.app = None
        Driver.__init__(self,name='CHESSID3B',defaults=self.gather_defaults(),overrides=overrides)
        ScatteringInstrument.__init__(self)

        self.client = PySpecClient(address='id3b.classe.cornell.edu',port='spec')
        self.client.connect()
        
        if self.config['reduced_data_dir'] is not None:
            os.chdir(self.config['reduced_data_dir'])

        self.__instrument_name__ = 'CHESS ID3B instrument'
        
        self.status_txt = 'Just started...'
        self.last_measured_transmission = [0,0,0,0]
        

    def pre_execute(self,**kwargs):
        pass

    def setReducedDataDir(self,path):
        self.config['reduced_data_dir'] = path
        os.chdir(path)

    def measureTransmission(self,set_empty_transmission=False,return_full=False):
        warnings.warn('measureTransmission is ill-defined on instruments with beamstop diodes.  Returning the last measured transmission.  To avoid this warning, call lastTransmission directly.',stacklevel=2)
        
    def lastTransmission(self,set_empty_transmission=False,return_full=False):
        open_beam = self.client.get_counter(self.config['i0_counter'])
        trans_beam = self.client.get_counter(self.config['diode_counter'])
        
        trans = trans_beam / open_beam
        
 
        
        if set_empty_transmission:
            #XXX! Should this be stored in config?
            self.config['empty transmission'] = trans
             
            retval = (trans,np.nan_to_num(open_beam).sum(),np.nan_to_num(sample_transmission).sum(),self.config['empty transmission'])
        elif self.config['empty transmission'] is not None:
            if return_full:
                retval = (trans / self.config['empty transmission'],open_beam,trans_beam,self.config['empty transmission'])
            else:
                retval = trans / self.config['empty transmission']
            self.app.logger.info(f'Scaling raw transmission of {trans*100}% using empty transmission of {self.config["empty transmission"]*100} % for reported sample transmission of {trans / self.config["empty transmission"]*100}%')
        else:
            if return_full:
                retval=(trans,open_beam,trans_beam.sum())
            else:
                retval = trans
        self.last_measured_transmission = retval
        self.status_txt = 'Idle'
        return retval

    @Driver.unqueued()        
    def getExposure(self):
        '''
            get the currently set exposure time

        '''
        return self.config['exposure']

        
    @Driver.unqueued()
    def getFilename(self):
        '''
            get the currently set file name

        '''
        return self.client.get_variable('DATAFILE').get()
   
    def setExposure(self,exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.config['exposure'] = exposure

    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        name = name.replace('\\','').replace('/','').replace(':','').replace('%','')
        self.client.run_cmd(f'newfile {name}')
    
    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def getData(self,**kwargs):
        specdir = self.client.get_variable('CWD')
        datafile = self.getFilename()
        scan_n = int(self.client.get_variable('SCAN_N'))

        datadir = Pathlib.path(specdir) / (f'datafile_{scan_n:03d}')
        
        try:
            det_str = kwargs['preferred_det']
        except KeyError:
            det_str = config['preferred_det']

        files = [x for x in datadir.iterdir() if det_str in str(x)]
        filepath = max(files,key=lambda x: int(x.parts[-1][-8:-5]))

        data = np.array(PIL.Image.open(filepath))
        return data

    def getMotorPosition(self,name):
        return self.client.get_motor(name).get_position()

    def moveAxis(self,axis,value,block=False):
        '''
        Moves a single axis using a connection to a labview vi.
        @param axis: the axis id or name of the motor to move
        @param value: the position of the motor to move to
        @param block: if True, this function will not return until the move is complete.
        '''
        mot = self.client.get_motor(axis).move(value)
    
        mot.move(value)
        if block:
            while(mot.moving):
                pass


    def _simple_expose(self,filename=None,exposure=None,block=False):
        if filename is None:
            filename=self.getFilename()
        else:
            self.setFilename(filename)

        if exposure is None:
            exposure=self.getExposure()
        else:
            self.setExposure(exposure)
        
        self.status_txt = f'Starting {exposure} s count named {filename}'
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {filename} for {exposure} s')


        self.client.run_cmd(f'tseries 1 {exposure}')
        if block:
            raise NotImplementedError()
            self.status_txt = 'Accessing Image'
            return self.getData(lv=lv)

    def expose(self,name=None,exposure=None,nexp=1,block=True,reduce_data=True,measure_transmission=True,save_nexus=True):
        if name is None:
            filename=self.getFilename()
        else:
            self.setFilename(filename)

        if exposure is None:
            exposure=self.getExposure()
        else:
            self.setExposure(exposure)
        
        self.status_txt = f'Starting {exposure} s count named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')


        self.client.run_cmd(f'tseries {nexp} {exposure}')
        #time.sleep(0.5)
        if block or reduce_data or save_nexus:
            raise NotImplementedError
            self.client.block_for_ready()
            self.status_txt = 'Accessing Image'
            data = self.getData()
            transmission = self.lastTransmission()
            if save_nexus:
                self.status_txt = 'Writing Nexus'
                self._writeNexus(data,name,name,transmission)
            if reduce_data:
                self.status_txt = 'Reducing Data'
                reduced = self.getReducedData(write_data=True,filename=name)
                #if save_nexus:
                    #self._appendReducedToNexus(reduced,name,name)
            self.status_txt = 'Instrument Idle'
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
