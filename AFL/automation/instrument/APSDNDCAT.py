import gc
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.PySpecClient import PySpecClient
import numpy as np # for return types in get data
import os
import pathlib
import PIL
import warnings

class APSDNDCAT(Driver):
    defaults = {}
    defaults['sample_axis'] = 'samp_h'
    defaults['measurement_positions'] = [-7.18,0.81,6.81]
    defaults['empty transmission'] = None
    defaults['transmission strategy'] = 'sum'
    defaults['exposure'] = 1.
    defaults['sample_thickness'] = 1.58
    defaults['i0_counter'] = 'cntr1'
    defaults['diode_counter'] = 'cntr3'
    defaults['symlink_data_dir'] = '/home/afl642/dnd-symlink-data/'
    defaults['source_data_dir'] = '/home/afl642/dnd-data/processing/%filename%/plot_files/'
    defaults['detectors'] = ['hs102','hs103','hs104']


    def __init__(self,overrides=None):
        '''
        connect to spec

        '''

        self.app = None
        Driver.__init__(self,name='APSDNDCAT',defaults=self.gather_defaults(),overrides=overrides)

        self.client = PySpecClient(address='localhost',port='spec') #SSH remote tunnel to cauliflower1.dnd.aps.anl.gov 
        self.client.connect()
        
        if self.config['reduced_data_dir'] is not None:
            os.chdir(self.config['reduced_data_dir'])

        self.__instrument_name__ = 'APS 5-ID-D DND-CAT'
        
        self.status_txt = 'Just started...'
        self.last_measured_transmission = [0,0,0,0]
        

    def pre_execute(self,**kwargs):
        pass

    def setReducedDataDir(self,path):
        self.config['reduced_data_dir'] = path
        os.chdir(path)

    @Driver.quickbar(qb={'button_text':'Measure Transmission',
        'params':{
        'set_empty_transmission':{'label':'Set Empty Trans?','type':'boolean','default':False}
        }})
    def measureTransmission(self,set_empty_transmission=False,return_full=False):
        warnings.warn('measureTransmission is ill-defined on instruments with beamstop diodes.  Returning the last measured transmission.  To avoid this warning, call lastTransmission directly.',stacklevel=2)
        return self.lastTransmission(set_empty_transmission=set_empty_transmission,return_full=return_full)        
    def lastTransmission(self,set_empty_transmission=False,return_full=False):
        open_beam = self.client.get_counter(self.config['i0_counter'])
        trans_beam = self.client.get_counter(self.config['diode_counter'])
        print(f"lastTransmission: open_beam={open_beam}")
        print(f"lastTransmission: trans_beam={trans_beam}")
        
        try:
            trans = trans_beam / open_beam
        except ZeroDivisionError:
            trans=0
 
        
        if set_empty_transmission:
            #XXX! Should this be stored in config?
            self.config['empty transmission'] = trans
             
            retval = (trans,open_beam,trans_beam,self.config['empty transmission'])
        elif self.config['empty transmission'] is not None:
            if return_full:
                retval = (trans / self.config['empty transmission'],open_beam,trans_beam,self.config['empty transmission'])
            else:
                retval = trans / self.config['empty transmission']
            self.app.logger.info(f'Scaling raw transmission of {trans*100}% using empty transmission of {self.config["empty transmission"]*100} % for reported sample transmission of {trans / self.config["empty transmission"]*100}%')
        else:
            if return_full:
                retval=(trans,open_beam,trans_beam)
            else:
                retval = trans
        self.last_measured_transmission = (trans/self.config['empty transmission'],open_beam,trans_beam,self.config['empty transmission'])
        self.status_txt = 'Idle'
        return retval
 
    def measureTransmissionQuick(self,exp=0.05,fn='align'):
            self._simple_expose(exposure=exp,name= fn,block=True)
            retval = self.lastTransmission()
            if self.config['open beam intensity'] is not None:
                retval = retval / self.config['open beam intensity']
            return retval          
    
    def interactiveLoad(self,name='lineup',cutoff_trans = 0.8,timeout=120):
        self.client.run_cmd('pil_off')
        self.client.run_cmd('opens')
        self.client.run_cmd(f'newfile {name}')
        start = datetime.datetime.now()
        timeout=datetime.timedelta(seconds=timeout)
        self.client.run_cmd('ct 0.1')
        baseline_trans = self.lastTransmission()
        
        while(datetime.datetime.now() - start)<timeout:
            self.client.run_cmd('ct 0.1')
            trans_ratio = self.lastTransmission()/baseline_trans

            if trans_ratio < cutoff_trans_ratio:
                self.app.logger.debug(f'Stopping load at transmission ratio = {trans_ratio}')
                break
        self.client.run_cmd('closes')        
        self.client.run_cmd('pil_on')
        
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

    @Driver.unqueued()
    def getLastFilePath(self,**kwargs):
        '''
            get the currently set file name

        '''
        specdir = self.client.get_variable('CWD').get()
        datafile = self.getFilename()
        scan_n = int(self.client.get_variable('SCAN_N').get())

        datadir = pathlib.Path(specdir) / (f'{datafile}_{scan_n:03d}')
        
        try:
            det_str = kwargs['preferred_det']
        except KeyError:
            det_str = self.config['preferred_det']

        files = [x for x in datadir.iterdir() if det_str in str(x)]
        filepath = max(files,key=lambda x: int(x.parts[-1][-8:-5]))
        return filepath

   
    def setExposure(self,exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.config['exposure'] = exposure

    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        name = name.replace('\\','').replace('/','').replace(':','').replace('%','')
        self.client.run_cmd(f'newfile {name}.dat SCAN_N')
    
    def getElapsedTime(self):
        isFlyScan = bool(self.client.get_variable('scanType_Fly').get() & self.client.get_variable('_stype').get() )
        if isFlyScan:
            return self.client.get_variable('_ctime').get()/self.client.get_variable('NPTS').get()
        else:
            return self.client.get_variable('_ctime').get()

    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def getData(self,**kwargs):
        try:
            filepath = self.getLastFilePath()
            data = np.array(PIL.Image.open(filepath))
        except FileNotFoundError:
            nattempts = 1
            while nattempts<11:
                nattempts = nattempts +1
                time.sleep(0.2)
                try:
                    filepath = self.getLastFilePath()
                    data = np.array(PIL.Image.open(filepath))
                except FileNotFoundError:
                    if nattempts == 10:
                        raise FileNotFoundError(f'could not locate file after {nattempts} tries')
                    else:
                        warnings.warn(f'failed to load file, trying again, this is try {nattempts}')
                else:
                    break
                
        return np.nan_to_num(data)

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


    def _simple_expose(self,name=None,exposure=None,block=False):
        if name is None:
            name=self.getFilename()
        else:
            self.setFilename(name)

        if exposure is None:
            exposure=self.getExposure()
        else:
            self.setExposure(exposure)
        
        self.status_txt = f'Starting {exposure} s count named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')


        self.client.run_cmd(f'loopscan 1 {exposure}')

        if block:
            raise NotImplementedError()
            self.status_txt = 'Accessing Image'
            return self.getData(lv=lv)

    @Driver.quickbar(qb={'button_text':'Expose',
        'params':{
        'name':{'label':'Name','type':'text','default':'test_exposure'},
        'exposure':{'label':'Exposure (s)','type':'float','default':5},
        'reduce_data':{'label':'Reduce?','type':'bool','default':True},
        'measure_transmission':{'label':'Measure Trans?','type':'bool','default':True}
        }})
    def expose(self,name=None,exposure=None,nexp=1,block=True,measure_transmission=True,make_symlinks=True):
        if name is None:
            name=self.getFilename()
        else:
            self.setFilename(name)

        if exposure is None:
            exposure=self.getExposure()
        else:
            self.setExposure(exposure)
        
        self.status_txt = f'Starting {exposure} s count named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')
        
        pos_trans = []
        pos_simple_trans = []
        pos_scan_n = []

        for idx,pos in enumerate(self.config['measurement_positions']):
            self.client.run_cmd(f'umv {self.config["sample_axis"]} {pos}')
            self.client.run_cmd(f'loopscan {nexp} {exposure}',block=True)
            
            #pos_raw_data.append(self.getData())
            #pos_reduced_data.append(self.getReducedData(write_data=True,filename=f'{name}_{idx}'))
            pos_trans.append(self.lastTransmission(return_full=True))
            pos_simple_trans.append(pos_trans[-1][0])
            pos_scan_n.append(self.client.get_variable('SCAN_N').get())    
        #time.sleep(0.5)
        if block or make_symlinks:
            self.client.block_for_ready()
            self.status_txt = 'Accessing Image'
            chosen_scan_n = pos_scan_n[np.argmin(pos_simple_trans)]
            self.app.logger.debug(f'Min transmission was {np.min(pos_simple_trans)} at index {np.argmin(pos_simple_trans)}; scan number was {chosen_scan_n}.  Other transmissions were {pos_simple_trans}')
            #data = pos_raw_data[np.argmin(pos_simple_trans)]
            transmission = pos_trans[np.argmin(pos_simple_trans)]
            #transmission = self.lastTransmission(return_full=True)

            if make_symlinks:
                clean_filename = self.getFilename().replace('.dat','')
                for det in self.config['detectors']:
                        datafile = self.config['source_data_dir'].replace('%filename%',clean_filename) + f'{clean_filename}_{det}_{chosen_scan_n}_0000.txt'
                        link_to_make = self.config['symlink_data_dir'] + f'{clean_filename}_{det}_{chosen_scan_n}_0000.txt'
                        os.symlink(datafile,link_to_make)

            self.status_txt = 'Instrument Idle'
            return transmission
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
        status.append(f'Last Measured Transmission: scaled={self.last_measured_transmission[0]} using empty cell trans of {self.last_measured_transmission[3]} with {self.last_measured_transmission[1]} raw counts in open/ {self.last_measured_transmission[2]} sample')
        status.append(f'Status: {self.status_txt}')
        #lmj = self._getLabviewValue("LMJ Status")
        
        #status.append(f'LMJ status: {"running, power on target = "+str(lmj[0]*lmj[1])+"W" if lmj[6]==1 else "not running"}')
        #status.append(f'Vacuum (mbar): {self._getLabviewValue("Pressure (mbar)")}')
        status.append(f'<a href="getData" target="_blank">Live Data (2D)</a>')
        status.append(f'<a href="getReducedData" target="_blank">Live Data (1D)</a>')
        status.append(f'<a href="getReducedData?render_hint=2d_img&reduce_type=2d">Live Data (2D, reduced)</a>')
        return status

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *

