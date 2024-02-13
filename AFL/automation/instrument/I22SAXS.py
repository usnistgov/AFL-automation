import time
import datetime
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument import ScatteringInstrument

import h5py #for Nexus file writing
import os
import pathlib
import warnings
import json
import datetime


import paramiko #general ssh connection client

def I22(Driver,ScatteringInstrument):
    defaults = {}
    defaults['username'] = ''
    defaults['address'] = ''
    defaults['port'] = 2222
    defaults['processed_base_path'] = '/mnt/i22_processed/i22-'
    defaults['reduced_data_suffix'] = '_saxs_Transmission_Averaged_Subtracted_IvsQ_processed.nxs'
    defaults['nframes'] = 1
    defaults['acq_time'] = 1
    defaults['acq_timeout'] = 120 
    defaults['file_read_timeout'] = 30
    
    
    def __init__(self):
        super.__init__(**kwargs)
        self.I22_client = paramiko.SSHClient()
        self.I22_client.load_system_host_keys()

        try:
            self.I22_client.connect()
        except:
            raise ValueError("cannot connect to host. check the username and address")
        self.raw_written=False
        self.integrated_written=False
        self.filename=None

    
    def expose(self, filename, empty = False, nframes=None, acq_time=None):
        """call the AFL_Acquisition command on I22"""

        if nframes is not None:
            self.config['nframes'] = nframes
        if acq_time is not None:
            self.config['acq_time'] = acq_time

        #this needs to be confirmed
        self.filename=filename
        if not empty:
            self.run_command = f"AFL_Acquisition(filename={filename},nframes={self.config['nframes']},acq_time={self.config['acq_time']})"
        else:
            self.run_command = f"AFL_Background(filename={filename},nframes={self.config['nframes']},acq_time={self.config['acq_time']})"
        self.raw_written = False
        
        self.app.logger.info(f'initiated run with command {self.run_command}')
        
        ssh_stdin, ssh_stdout, ssh_stderr = self.I22_client.exec_command(self.run_command)
        start_time = datetime.datetime.now()
        timeout = start_time + datetime.timedelta(seconds=self.config['acq'])
        output = ssh_stdout.readlines()
        self.app.logger.info(f'  {output}')
        while 'successfully' not in output and datetime.datetime.now() < timeout:
            output = ssh_stdout.readlines()
            if len(output) > 0:
                self.app.logger.info(f'  {output}')
            time.sleep(0.1)

            
        
        self.raw_written=True
        
        return self.raw_written

    def background(self):
        """
        calls the AFL_Background command on I22
        """
        pass
        return

    def read_integrated(self,scanid):
        """ 
        Scans the appropriate directory for the filename of the data collected with filename
        """
        fname = f"{self.config['processed_base_path']}scanid{self.config['reduced_data_suffix']}"

        #check if file exists
        start_time = datetime.datetime.now()
        timeout = start_time + datetime.timedelta(seconds = self.config['file_read_timeout'])
        while not os.path.isfile(fname) and datetime.datetime.now() < timeout:
            time.sleep(0.1)
            
        with h5py.File(fname) as f:
            I = f['processed']['result']['data'][:]
            q = f['processed']['result']['q'][:]
            err = f['processed']['result']['errors'][:]

        
        # construct an xarray with this and return it?
        
        return (I,q,err)


        
        
