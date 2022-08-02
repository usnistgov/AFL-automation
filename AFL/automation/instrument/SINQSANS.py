import gc
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL
import warnings
import re,telnetlib #for sics telnet comms


class SINQSANS(ScatteringInstrument,Driver):
    defaults = {}
    defaults['sics_host'] = 'sans.psi.ch'
    defaults['sics_port'] = 1301
    defaults['user_login'] = 'User 22lns1' 
    defaults['empty transmission'] = None
    defaults['transmission strategy'] = 'sum'
    defaults['reduced_data_dir'] = '/mnt/home/chess_id3b/beaucage/211012-data'
    defaults['exposure'] = 1.
    defaults['absolute_calibration_factor'] = 1
    defaults['data_path'] = '/home/afl642'

    defaults['pixel1'] = 0.075 #pixel y size in m
    defaults['pixel2'] = 0.075 #pixel x size in m
    defaults['num_pixel1'] = 128
    defaults['num_pixel2'] = 128
    def __init__(self,overrides=None):
        '''
        connect to spec

        '''

        self.app = None
        Driver.__init__(self,name='SINQSANS',defaults=self.gather_defaults(),overrides=overrides)
        ScatteringInstrument.__init__(self)

        self.client = SICSClient(self.config['sics_host'],self.config['sics_port'],self.config['user_login'])
        
        if self.config['reduced_data_dir'] is not None:
            os.chdir(self.config['reduced_data_dir'])

        self.__instrument_name__ = 'PSI SINQ SANS instrument'
        
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
                retval=(trans,open_beam,trans_beam.sum())
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
        return self.client.ask_param('sample')

    @Driver.unqueued()
    def getLastFilePath(self,**kwargs):
        '''
            get the currently set file name

        '''
        sicsdatanumber = self.client.ask_param('sicsdatanumber')
        filepath = pathlib.Path(self.config['data_path'])/f'sans2022n0{sicsdatanumber}.hdf'
        return filepath

   
    def setExposure(self,exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.app.config['exposure'] = exposure

    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        name = name.replace('\\','').replace('/','').replace(':','').replace('%','')
        self.client.set_param('sample',name)
    
    def getElapsedTime(self):
        raise NotImplementedError 

    def readH5(self,filepath,update_config=False,**kwargs):
        out_dict = {}
        with open(filepath,'r') as h5:
            out_dict['counts']     = h5['entry1/data1/counts'][()]
            out_dict['name']       = h5['entry1/sample/name'][()]
            out_dict['dist']       = h5['entry1/SANS/detector/x_position'][()]/1000
            out_dict['wavelength'] = h5['entry1/data1/lambda'][()]*1e-9,
            out_dict['beam_center_x']  = h5['entry1/SANS/detector/beam_center_x'][()]
            out_dict['beam_center_y']  = h5['entry1/SANS/detector/beam_center_y'][()]
            out_dict['poni2']      = h5['entry1/SANS/detector/beam_center_x'][()]*self.config['pixel1']
            out_dict['poni1 ']     = h5['entry1/SANS/detector/beam_center_y'][()]*self.config['pixel2']

        if update_config:
            self.config['wavelength'] = out_dict['wavelength']
            self.config['dist'] = out_dict['dist']
            self.config['poni1'] = out_dict['poni1']
            self.config['poni2'] = out_dict['poni2']

        return out_dict

    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def getData(self,**kwargs):
        try:
            filepath = self.getLastFilePath()
            data = self.readH5(filepath)['counts']
        except FileNotFoundError:
            nattempts = 1
            while nattempts<11:
                nattempts = nattempts +1
                time.sleep(0.2)
                try:
                    filepath = self.getLastFilePath()
                    data = self.readH5(filepath)['counts']
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


        self.client.run_cmd(f'opens')
        
        self.client.run_cmd(f'tseries 1 {exposure}')
        self.client.run_cmd(f'closes')

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
    def expose(self,name=None,exposure=None,nexp=1,block=True,reduce_data=True,measure_transmission=True,save_nexus=True):
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
        pos_raw_data = []
        pos_simple_trans = []
        pos_reduced_data = []

        for idx,pos in enumerate(self.config['measurement_positions']):
            self.client.run_cmd(f'umv samx {pos}')
            self.client.run_cmd(f'opens')
            self.client.run_cmd(f'tseries {nexp} {exposure/10}')
            self.client.run_cmd(f'tseries {nexp} {exposure}',block=True)
            self.client.run_cmd(f'closes')
            
            pos_raw_data.append(self.getData())
            pos_reduced_data.append(self.getReducedData(write_data=True,filename=f'{name}_{idx}'))
            pos_trans.append(self.lastTransmission(return_full=True))
            pos_simple_trans.append(pos_trans[-1][0])
                
        #time.sleep(0.5)
        if block or reduce_data or save_nexus:
            self.client.block_for_ready()
            self.status_txt = 'Accessing Image'
            self.app.logger.debug(f'Min transmission was {np.min(pos_simple_trans)} at index {np.argmin(pos_simple_trans)}; returning that data.  Other transmissions were {pos_simple_trans}')
            data = pos_raw_data[np.argmin(pos_simple_trans)]
            transmission = pos_trans[np.argmin(pos_simple_trans)]
            #transmission = self.lastTransmission(return_full=True)
            if save_nexus:
                self.status_txt = 'Writing Nexus'
                self._writeNexus(data,name,name,transmission)
            if reduce_data:
                self.status_txt = 'Reducing Data'
                reduced = pos_reduced_data[np.argmin(pos_simple_trans)]
                print(np.shape(reduced))
                np.savetxt(f'{name}_chosen_r1d.csv',np.transpose(reduced),delimiter=',')
                #self.getReducedData(write_data=True,filename=name)
                #if save_nexus:
                    #self._appendReducedToNexus(reduced,name,name)
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

class SICSTelnetClient():

    def __init__(self,host,port,login):
        self.host = host
        self.port = port

        self.conn = telnetlib.Telnet(host,port)
        self.conn.open(host,port)
        self.conn.write(f'sicslogin {login}\r\n'.encode('utf-8'))
        time.sleep(1)
        resp = self.conn.read_very_eager().decode()
        if resp[0:2] != 'OK':
            raise Exception(f'received unexpected answer from SICS: {resp}')

    def ask_param(self,param):
        cmd = f'{param}\r\n'.encode('utf-8')
        self.conn.write(cmd)
        time.sleep(1)
        response = self.conn.read_very_eager().decode()
        regexsplit = re.findall(r'(.*?) = (.*?)\r\n',response)
        return regexsplit[0][1]

    def set_param(self,param,val):
        cmd = f'{param} {val}\r\n'.encode('utf-8')
        self.conn.write(cmd)
        response = self.conn.read_very_eager()
        return response.decode().replace(r'\r\n','')

    def __del__(self):
        self.conn.close()
