import time
import datetime
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument import ScatteringInstrument

import h5py #for Nexus file writing
import os
import pathlib
import warnings
import json


import paramiko #general ssh connection client

def I22(Driver,ScatteringInstrument):
    def __init__(self,username,address,port=5000):
        self.I22_client = paramiko.SSHClient()
        self.I22_client.load_system_host_keys()
        self.username = username
        self.address = address
        self.port = port
        
        
        try:
            self.I22_client.connect()
        except:
            raise ValueError("cannot connect to host. check the username and address")
        self.raw_written=False
        self.integrated_written=False
        self.filename=None

    def expose(self, filename, nframes, acq_time):
        """call the AFL_Acquisition command on I22"""

        #this needs to be confirmed
        self.filename=filename
        self.run_command = f"AFL_Acquisition(filename={filename},nframes={nframes},acq_time={acq_time})"
        self.raw_written = False
        
        ssh_stdin, ssh_stdout, ssh_stderr = self.I22_client.exec_command(self.run_command)
        output = ssh_stdout.readlines()
        while 'successfully' not in output:
            output = ssh_stdout.readlines()
            time.sleep(0.1)
            print('waiting for raw data to be written')
        

        self.raw_written=True
        
        return self.raw_written

    def background(self):
        """
        calls the AFL_Background command on I22
        """
        pass
        return

    def read_integrated(self):
        """ 
        Scans the appropriate directory for the filename of the data collected with filename
        """
        
        self.integrated_written=False
        
        return self.integrated_written


        
        
