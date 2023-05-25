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
import json


class SINQSANS(ScatteringInstrument,Driver):
    defaults = {}
    defaults['sics_host'] = 'sans.psi.ch'
    defaults['sics_port'] = 1301
    defaults['user_login'] = 'User 22lns1'  #User  23lns1
    defaults['empty transmission'] = 1
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

        self.client = SICSTelnetClient(self.config['sics_host'],self.config['sics_port'],self.config['user_login'])
        self.status_monitor_client =  SICSTelnetClient(self.config['sics_host'],self.config['sics_port'],self.config['user_login'])
       
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
        self._simple_expose(exposure=2,block=True,mode='trans')
        
        try:
            cts = int(self.client.ask_param('banana sum 40 80 40 80'))
        except ValueError:
            cts = int(self.client.ask_param('banana sum 40 80 40 80'))

        monitor_cts = 10 
        trans = cts/monitor_cts
        
        if set_empty_transmission:
            self.config['empty transmission'] = trans
        self.last_measured_transmission = (trans,monitor_cts,cts,self.config['empty transmission'])
        if return_full:
            return self.last_measured_transmission
        else:
            return trans/self.config['empty transmission']

    def lastMeasuredTransmission(self):
        return self.last_measured_transmission
        
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
        count = 0
        while True:
            sicsdatanumber = self.client.ask_param('sicsdatanumber')
            try:
                int(sicsdatanumber)
            except ValueError: 
                if count>10:
                    raise ValueError('Could not read sicsdatanumber!')
                time.sleep(0.5)
            else:
                break
            count+=1

        filepath = pathlib.Path(self.config['data_path'])/f'sans2022n0{sicsdatanumber}.hdf'
        if self.app is not None:
            self.app.logger.debug(f'Last file found to be {filepath}')
        else:
            print(f'Last file found to be {filepath}')
        return filepath

   
    def setExposure(self,exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.config['exposure'] = exposure

    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        name = name.replace('\\','').replace('/','').replace(':','').replace('%','')
        self.client.set_param('sample',name)
    
    def getElapsedTime(self):
        raise NotImplementedError 

    def readH5(self,filepath,update_config=False,**kwargs):
        out_dict = {}
        with h5py.File(filepath,'r') as h5:
            out_dict['counts']         = h5['entry1/data1/counts'][()]
            # out_dict['name']           = h5['entry1/sample/name'][()]
            # out_dict['dist']           = h5['entry1/SANS/detector/x_position'][()]/1000
            # out_dict['wavelength']     = h5['entry1/data1/lambda'][()]*1e-9,
            # out_dict['beam_center_x']  = h5['entry1/SANS/detector/beam_center_x'][()]
            # out_dict['beam_center_y']  = h5['entry1/SANS/detector/beam_center_y'][()]
            # out_dict['poni2']          = h5['entry1/SANS/detector/beam_center_x'][()]*self.config['pixel1']
            # out_dict['poni1 ']         = h5['entry1/SANS/detector/beam_center_y'][()]*self.config['pixel2']

        # if update_config:
        #     self.config['wavelength'] = out_dict['wavelength']
        #     self.config['dist']       = out_dict['dist']
        #     self.config['poni1']      = out_dict['poni1']
        #     self.config['poni2']      = out_dict['poni2']

        return out_dict

    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def getData(self,**kwargs):
        try:
            filepath = self.getLastFilePath()
            data = self.readH5(filepath)['counts']
        except (FileNotFoundError,OSError,KeyError):
            nattempts = 1
            while nattempts<31:
                nattempts = nattempts +1
                time.sleep(1.0)
                try:
                    filepath = self.getLastFilePath()
                    data = self.readH5(filepath)['counts']
                except (FileNotFoundError,OSError,KeyError):
                    if nattempts == 30:
                        raise FileNotFoundError(f'could not locate file after {nattempts} tries')
                    else:
                        warnings.warn(f'failed to load file, trying again, this is try {nattempts}')
                else:
                    break
                
        return np.nan_to_num(data)


    def _simple_expose(self,name=None,exposure=None,mode='scatt',aects=1e6,block=False):
        if name is None:
            name=self.getFilename()
        else:
            self.setFilename(name)

        if exposure is None:
            exposure=self.getAutoExposure(desired_counts = aects)
        
        #self.setExposure(exposure)
        
        self.status_txt = f'Starting {exposure} moni count named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} moni cts')

        if mode == 'scatt':
            self.client.send_cmd(f'MLscatt {self.config["exposure"]}')
        else:
            self.client.send_cmd(f'MLtrans {self.config["exposure"]}')
        if block:
            time.sleep(2)
            self.blockForCompleted()
            time.sleep(0.5)
            self.client.flush_buffer()
    
    def getAutoExposure(self,short_count_dur=2,desired_counts = 1000000):
        self.client.send_cmd(f'count moni {short_count_dur} n')
        time.sleep(1)
        self.blockForIdle()
        self.client.conn.read_lazy()
        time.sleep(1)
        try:
            counts = int(self.client.ask_param('banana sum 0 127 0 127'))
        except ValueError:
            counts = int(self.status_monitor_client.ask_param('banana sum 0 127 0 127'))
        count_rate = counts / short_count_dur
        proposed_time = (desired_counts / count_rate)
        if proposed_time>500:
            print(f'with {counts} in a {short_count_dur} exposure, I would like to measure {proposed_time}, but that seems too high.')
            print(f'setting to 500 instead.')
            proposed_time = 500
        if proposed_time < 5:
            print(f'with {counts} in a {short_count_dur} exposure, I would like to measure {proposed_time}, but that seems too low.')
            print(f'setting to 5 instead.')
            proposed_time = 5
        return proposed_time

    @Driver.quickbar(qb={'button_text':'Expose',
        'params':{
        'name':{'label':'Name','type':'text','default':'test_exposure'},
        'exposure':{'label':'Exposure (s)','type':'float','default':5},
        'reduce_data':{'label':'Reduce?','type':'bool','default':True},
        'measure_transmission':{'label':'Measure Trans?','type':'bool','default':True}
        }})
    def expose(self,name=None,exposure=None,block=True,reduce_data=True,measure_transmission=True,save_nexus=True):
        if name is None:
            name=self.getFilename()
        else:
            self.setFilename(name)
      
        if measure_transmission:
            self.measureTransmission() 
       
        if exposure is not None:
            #time.sleep(5)
            #print('finding auto exposure counts..:')
            #exposure=self.getAutoExposure()
            self.setExposure(exposure)
        
        
        pre_sicsdatanumber = self.client.ask_param('sicsdatanumber')
        if self.data is not None:
            self.data['pre_sicsdatanumber'] = pre_sicsdatanumber
        self.status_txt = f'Starting {exposure} moni count named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} moni cts')
        
        self.client.send_cmd(f'MLscatt {self.config["exposure"]}')
        if block or reduce_data or save_nexus:
            self.blockForCompleted()
            self.client.flush_buffer()
            
            try:
                 trash = int(self.client.ask_param('banana sum 40 80 40 80'))
            except ValueError:
                 trash = int(self.client.ask_param('banana sum 40 80 40 80'))

            if save_nexus:
                data = self.getData()
                normalized_sample_transmission  = self.last_measured_transmission[0]
                if self.data is not None:
                    self.data['raw_data'] = data
                    self.data['normalized_sample_transmission'] = normalized_sample_transmission
                self.status_txt = 'Writing Nexus'
                self._writeNexus(data,name,name,normalized_sample_transmission)

            if reduce_data:
                self.status_txt = 'Reducing Data'
                reduced = self.getReducedData(write_data=True,filename=name)
                if self.data is not None:
                    self.data['reduced_data'] = reduced
                np.savetxt(f'{name}_chosen_r1d.csv',np.transpose(reduced),delimiter=',')

                normalized_sample_transmission  = self.last_measured_transmission[0]
                open_flux = self.last_measured_transmission[1]
                sample_flux = self.last_measured_transmission[2]
                empty_cell_transmission = self.last_measured_transmission[3]
                sample_transmission = normalized_sample_transmission*empty_cell_transmission
                
                if self.data is not None:
                    self.data['normalized_sample_transmission'] = normalized_sample_transmission
                    self.data['open_flux'] = open_flux
                    self.data['sample_flux'] = sample_flux
                    self.data['empty_cell_transmission'] = empty_cell_transmission
                    self.data['sample_transmission'] = sample_transmission


                if save_nexus:
                    self._appendReducedToNexus(reduced,name,name)

                out = {}
                out['normalized_sample_transmission'] = normalized_sample_transmission
                out['open_flux'] = open_flux
                out['sample_flux'] = sample_flux
                out['empty_cell_transmission'] = empty_cell_transmission
                out['sample_transmission'] = sample_transmission
                with open(f'{name}_trans.json','w') as f:
                    json.dump(out,f)

            self.status_txt = 'Instrument Idle'
         
    def blockForIdle(self):
        self.status_monitor_client.success()

    def blockForCompleted(self):
        flag = True
        while flag:
            resp = self.client.conn.read_until(b'\r\n').decode()
            print(resp)
            flag = ('ML completed' not in resp)
            time.sleep(0.1)

    def getStatus(self):
        status = self.status_monitor_client.ask_param('el737 RS')
        return status

    def isCounting(self):
        return bool(int(self.getStatus()))


               
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

    def ask_param(self,param,second_try = False):
        cmd = f'{param}\r\n'.encode('utf-8')
        self.conn.write(cmd)
        print(f'sending {cmd} to server')
        time.sleep(1)
        response = self.conn.read_very_eager().decode()
        if 'ERROR: Busy' in response:
            time.sleep(1)
            print('rcvd busy response; retrying')
            return self.ask_param(param)

        try:
            regexsplit = re.findall(r'(.*?) = (.*?)\r\n',response)
            retval = regexsplit[0][1]
        except IndexError:
            self.conn.read_lazy()
            if second_try:
                raise IndexError(f'weird answer from server: {response}, cannot parse after 2 tries.') 
            time.sleep(1) #cool down incase you were just too fast
            retval = self.ask_param(param,second_try = True)    
        return retval

    def set_param(self,param,val):
        cmd = f'{param} {val}\r\n'.encode('utf-8')
        print(f'sending {cmd} to server')
        self.conn.write(cmd)
        response = self.conn.read_very_eager()
        return response.decode().replace(r'\r\n','')

    def send_cmd(self,cmd):
        cmd = f'{cmd}\r\n'.encode('utf-8')
        print(f'sending {cmd} to server')
        self.conn.write(cmd)
        response = self.conn.read_very_eager().decode()
        print(f'head back: {response}')
        return response
    def success(self):
        cmd = f'success\r\n'.encode('utf-8')
        print(f'sending {cmd} to server')
        self.conn.write(cmd)
        response = self.conn.read_until(b'\r\n').decode()
        return response
    def __del__(self):
        self.conn.close()
    def flush_buffer(self):
        flag = True
        while flag:
            resp = self.conn.read_lazy() 
            print(resp)
            flag = (resp != b'')
            time.sleep(0.2)
if __name__ == '__main__':
    import matplotlib.pyplot as plt
    sans = SINQSANS()

