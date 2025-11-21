import gc
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
import numpy as np # for return types in get data
import h5py #for Nexus file reading
import lazy_loader as lazy
epics = lazy.load("epics", require="AFL-automation[neutron-scattering]")
import os
import pathlib
import warnings
Matilda = lazy.load("matilda", require="AFL-automation[usaxs]")

class APSUSAXS(Driver):
    defaults = {}
    defaults['sample_thickness'] = 1.58
    defaults['run_initiate_pv'] = '9idcLAX:AutoCollectionStart'
    defaults['script_name_pv'] = '9idcLAX:AutoCollectionStrInput'
    defaults['instrument_status_pv'] = '9idcLAX:state'
    defaults['script_path'] = '/mnt/share1/USAXS_data/2022-06/'
    defaults['instrument_running_pv'] = '9idcLAX:dataColInProgress'
    defaults['script_template_file'] = 'AFL-template.mac'
    defaults['script_file'] = 'AFL.mac'
    defaults['magic_project_key'] = '!!AFL-SETNAME!!'
    defaults['magic_filename_key'] = '!!AFLREPLACEME!!'
    defaults['magic_xpos_key'] = '!!AFLXPOS!!'
    defaults['magic_ypos_key'] = '!!AFLYPOS!!'
    defaults['active_holder'] = '6A'
    defaults['script_write_cooldown'] = 1 
    defaults['platemap'] = {
                         '6A':{
                     'SlotA':
                        {
                          'x0': 0,
                          'y0': 0,
                          'x_step': 9,
                          'y_step': 9,
                          'x_per_y_skew': .5,
                          'y_per_x_skew': -(8/12)*.5,
                        },
                        'SlotB':
                        {
                          'x0': -150,
                          'y0': -150,
                          'x_step': 9,
                          'y_step': 9,
                          'x_per_y_skew': 1,
                          'y_per_x_skew': -(8/12)*1,
                        },
                        'SlotC':
                        {
                          'x0': 150,
                          'y0': 150,
                          'x_step': 9,
                          'y_step': 9,
                          'x_per_y_skew': -8,
                          'y_per_x_skew': -(8/12)*-8,
                        },

                    }
                    }
    defaults['file_read_max_retries'] = 20
    defaults['file_read_retry_sleep'] = 15.0
    defaults['file_data_check_key'] = 'CalibratedData'  # Dictionary key to check for None
    defaults['file_blank_check_key'] = 'BlankData'  # Dictionary key to check for None
    defaults['userdir_pv'] = 'usxLAX:userDir'
    defaults['datadir_pv'] = 'usxLAX:sampleDir'
    defaults['next_fs_order_n_pv'] = 'usxLAX:USAXS:FS_OrderNumber'

    def __init__(self,overrides=None):
        '''
        connect to usaxs via EPICS

        '''

        self.readMyNXcanSAS = lazy.load("matilda.hdf5code.readMyNXcanSAS", require="AFL-automation[usaxs]")

        self.app = None
        Driver.__init__(self,name='APSUSAXS',defaults=self.gather_defaults(),overrides=overrides)
        
        
        self.__instrument_name__ = 'APS USAXS instrument'
        
        self.status_txt = 'Just started...'
        self.filename = 'default'
        self.filename_prefix = 'AFL'
        self.project = 'AFL'
        self.xpos = 0
        self.ypos = 0

    def pre_execute(self,**kwargs):
        pass


    @Driver.unqueued()
    def getFilenamePrefix(self):
        '''
            get the currently set file name prefix

        '''
        return self.filename_prefix
    
    @Driver.unqueued()
    def setFilenamePrefix(self,prefix):
        '''
            set the currently set file name prefix

        '''
        self.filename_prefix = prefix
        if self.app is not None:
            self.app.logger.debug(f'Setting filename prefix to {prefix}')

    @Driver.unqueued()
    def getFilename(self):
        '''
            get the currently set file name

        '''
        return self.filename


    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        self.filename = name
    @Driver.unqueued()
    def getProject(self):
        '''
           get the currently set file name
        
        '''
        return self.project

    def _coords_from_tuple(self,slot,row,col):
        if len(row)>1:
            raise ValueError('row must be a single letter')
        row = ord(row) & 31
        col = int(col)

        geom = self.config['platemap'][self.config['active_holder']][slot]

        return (geom['x0'] + (row-1)*geom['x_step'] + geom['x_per_y_skew']*(col-1),
                geom['y0'] + (col-1)*geom['y_step'] + geom['y_per_x_skew']*(row-1))
    
    def setProject(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        self.project = name

    def _writeUSAXSScript(self):
        '''
        burn the current filename and project name into a USAXS script
        '''

        lines = []
        with open(pathlib.Path(self.config['script_path'])/self.config['script_template_file'],'r') as f:
            for line in f:
                s = line.replace(self.config['magic_project_key'],self.project)
                s = s.replace(self.config['magic_filename_key'],self.filename)
                s = s.replace(self.config['magic_xpos_key'],str(self.xpos))
                s = s.replace(self.config['magic_ypos_key'],str(self.ypos))
                s = s.replace('\r','')
                s = s.replace('\n','')
                lines.append(s)
        with open(pathlib.Path(self.config['script_path'])/self.config['script_file'],'w') as f:
            for line in lines:
                f.write(line+'\r\n')

    def _safe_read_file(self, filepath, filename, is_usaxs=True, is_blank=False):
        '''
        Safely read a USAXS file with retry logic.
        
        Checks if file exists, then calls readMyNXcanSAS. If the specified
        dictionary entry is None, retries after sleeping. Continues until
        max retries are reached or the file is successfully read.
        
        Parameters
        ----------
        filepath : pathlib.Path
            Path to the directory containing the file
        filename : str
            Name of the file to read
            
        Returns
        -------
        dict
            Dictionary returned by readMyNXcanSAS
            
        Raises
        ------
        FileNotFoundError
            If the file does not exist
        RuntimeError
            If the file cannot be read successfully after max retries
        '''
        full_path = filepath / filename
        
        # Check if file exists
        if not full_path.exists():
            raise FileNotFoundError(f'File does not exist: {full_path}')
        
        max_retries = self.config['file_read_max_retries']
        retry_sleep = self.config['file_read_retry_sleep']

        if is_blank:
            check_key = self.config['file_blank_check_key']
        else:
            check_key = self.config['file_data_check_key']
        
        for attempt in range(max_retries):
            try:
                data_dict = self.readMyNXcanSAS(filepath, filename,is_usaxs=is_usaxs)
                
                # Check if the specified key is None
                if check_key not in data_dict:
                    if self.app is not None:
                        self.app.logger.warning(
                            f'Key "{check_key}" not found in data dictionary. '
                            f'Available keys: {list(data_dict.keys())}'
                        )
                    # If key doesn't exist, treat as failure and retry
                    if attempt < max_retries - 1:
                        time.sleep(retry_sleep)
                        continue
                    else:
                        raise RuntimeError(
                            f'Key "{check_key}" not found in data dictionary after {max_retries} attempts'
                        )
                
                if data_dict[check_key]['Intensity'] is None:
                    if attempt < max_retries - 1:
                        if self.app is not None:
                            self.app.logger.debug(
                                f'Key ["{check_key}"]["Intensity"] is None, retrying in {retry_sleep}s '
                                f'(attempt {attempt + 1}/{max_retries})'
                            )
                        time.sleep(retry_sleep)
                        continue
                    else:
                        raise RuntimeError(
                            f'Key ["{check_key}"]["Intensity"] is None after {max_retries} attempts. '
                            f'File may not be fully written: {full_path}'
                        )
                
                # Success - data is valid
                if self.app is not None:
                    self.app.logger.debug(f'Successfully read file {filename} on attempt {attempt + 1}')
                return data_dict
                
            except Exception as e:
                if attempt < max_retries - 1:
                    if self.app is not None:
                        self.app.logger.warning(
                            f'Error reading file {filename} (attempt {attempt + 1}/{max_retries}): {e}. '
                            f'Retrying in {retry_sleep}s...'
                        )
                    time.sleep(retry_sleep)
                    continue
                else:
                    raise RuntimeError(
                        f'Failed to read file {full_path} after {max_retries} attempts. '
                        f'Last error: {e}'
                    )
        
        # Should never reach here, but just in case
        raise RuntimeError(f'Failed to read file {full_path} after {max_retries} attempts')

    @Driver.quickbar(qb={'button_text':'Expose',
        'params':{
        'name':{'label':'Name','type':'text','default':'test_exposure'},
        'exposure':{'label':'Exposure (s)','type':'float','default':5},
        'reduce_data':{'label':'Reduce?','type':'bool','default':True},
        'measure_transmission':{'label':'Measure Trans?','type':'bool','default':True}
        }})
    def expose(self, name = None, block = True, read_USAXS = True, read_SAXS = True):
        if name is None:
            name=self.getFilenamePrefix()
        else:
            self.setFilenamePrefix(name)
        self.status_txt = f'Starting USAXS/SAXS/WAXS scan named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting USAXS/SAXS/WAXS exposure with name {name}')
        self.status_txt = 'Writing script...'
        self._writeUSAXSScript()
        self.status_txt = 'Waiting for script save...'
        time.sleep(self.config['script_write_cooldown'])
        epics.caput(self.config['script_name_pv'],self.config['script_file'])
        time.sleep(0.1)
        epics.caput(self.config['run_initiate_pv'],1)
        self.status_txt = 'Run started!'

        time.sleep(0.5)
        if block or reduce_data:
            time.sleep(20)
            self.block_for_run_finish()
            self.status_txt = 'Instrument Idle'
        
        if "blank" in name.lower():
            is_blank = True
        else:
            is_blank = False
        
        user_dir = epics.caget(self.config['userdir_pv'],as_string=True)
        data_dir = epics.caget(self.config['datadir_pv'],as_string=True)
        fs_order_n = epics.caget(self.config['next_fs_order_n_pv']) - 1.0 # need to subtract 1 because the order number is incremented after the scan starts
        filename= f"{self.filename_prefix}_{fs_order_n:04d}.h5"
        if read_USAXS:
            filepath_usaxs = pathlib.Path(user_dir) / (str(data_dir) + '_usaxs') / filename
            data_dict_usaxs = self._safe_read_file(filepath_usaxs, filename,is_usaxs=True,is_blank=is_blank)

            self.data.add_array('USAXS_q',data_dict_usaxs['CalibratedData']['Q'])
            self.data.add_array('USAXS_I',data_dict_usaxs['CalibratedData']['Intensity'])
            self.data.add_array('USAXS_dI',data_dict_usaxs['CalibratedData']['Error'])
            self.data['USAXS_Filepath'] = str(filepath_usaxs)
            self.data['USAXS_Filename'] = filename
            self.data['USAXS_name'] = name
            self.data['USAXS_blank'] = is_blank

        if read_SAXS:
            filepath_saxs = pathlib.Path(user_dir) / (str(data_dir) + '_saxs') / filename
            data_dict_saxs = self._safe_read_file(filepath_saxs, filename,is_usaxs=False,is_blank=is_blank)

            self.data.add_array('SAXS_q',data_dict_saxs['CalibratedData']['Q'])
            self.data.add_array('SAXS_I',data_dict_saxs['CalibratedData']['Intensity'])
            self.data.add_array('SAXS_dI',data_dict_saxs['CalibratedData']['Error'])
            self.data['SAXS_Filepath'] = str(filepath_saxs)
            self.data['SAXS_Filename'] = filename
            self.data['SAXS_name'] = name
            self.data['SAXS_blank'] = is_blank

    def block_for_run_finish(self):
        while self.getRunInProgress():
            time.sleep(5)
        
    def getRunStatus(self):
        return epics.caget(self.config['instrument_status_pv'],as_string=True)
    
    def setPosition(self,plate,row,col,x_offset=0,y_offset=0):
        (self.xpos,self.ypos) = self._coords_from_tuple(plate,row,col)
        self.xpos+=x_offset
        self.ypos+=y_offset
        
    def getRunInProgress(self):
        return epics.caget(self.config['instrument_running_pv']) 
    
               
    def status(self):
        status = []
        status.append(f'Status: {self.status_txt}')
        status.append(f'EPICS status: {self.getRunStatus()}')
        status.append(f'Next X: {self.xpos}')
        status.append(f'Next Y: {self.ypos}')
        status.append(f'Next filename: {self.filename}')
        status.append(f'Next project: {self.project}')
        return status
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *


