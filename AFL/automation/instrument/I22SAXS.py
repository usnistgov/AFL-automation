import time
import datetime
from AFL.automation.APIServer.Driver import Driver

import h5py #for Nexus file writing
import os
import pathlib
import warnings
import json
import datetime
import xarray as xr
import numpy as np

import paramiko #general ssh connection client

class I22SAXS(Driver):
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
    defaults['pos_list'] = []
    defaults['empty_scan_id'] = '' 
    defaults['data_read_cooldown'] = 5

    def __init__(self,overrides=None,**kwargs):
        self.app = None
        Driver.__init__(self,name='I22SAXS',defaults=self.gather_defaults(),overrides=overrides)


        self.I22_client = paramiko.SSHClient()
        self.I22_client.load_system_host_keys()
    
        try:
            self.I22_client.connect(self.config['address'],username=self.config['username'],port=self.config['port'])

        except:
            raise ValueError("cannot connect to host. check the username and address")
        self.raw_written=False
        self.integrated_written=False
        self.filename=None

    
    def _expose(self, filename, xpos, ypos, empty = False, nframes=None, acq_time=None):
        """
        Perform an AFL acquision sequence on I22
        """

        if nframes is not None:
            self.config['nframes'] = nframes
        if acq_time is not None:
            self.config['acq_time'] = acq_time

        if not empty:
            self.run_command = f"AFL_Acquisition(scan_title='{filename}',background_frame = '{self.config['empty_scan_id']}' ,x_position={xpos},y_position={ypos},num_frames={self.config['nframes']},frame_time={self.config['acq_time']})"
        else:
            self.run_command = f"AFL_Background(scan_title='{filename}',x_position={xpos},y_position={ypos},num_frames={self.config['nframes']},frame_time={self.config['acq_time']})"
        self.raw_written = False
        
        self.app.logger.info(f'initiated run with command {self.run_command}')
        
        ssh_stdin, ssh_stdout, ssh_stderr = self.I22_client.exec_command(self.run_command)
        start_time = datetime.datetime.now()
        timeout = start_time + datetime.timedelta(seconds=self.config['acq_timeout'])
        ssh_stdout.channel.recv_exit_status()

        counter_headers = []
        counter_values = []
        counters = {}
        


        for output in ssh_stdout.readlines():
            if len(output) > 0:
                self.app.logger.info(f'  {output}')
                output.replace('\n','')
                if len(output.split('\t'))>1:
                    if len(counter_headers) > 0:
                        # these are values
                        counter_values = output.split('\t')
                        assert(len(counter_values) == len(counter_headers),'Mismatch or error parsing counters')
                        for i,name in enumerate(counter_headers):
                            counters[name] = float(counter_values[i])
                    else:
                        counter_headers = output.split('\t')
                elif 'successfully' in output:
                    scanid = int(output.split(". Scan ")[1].split(" ended successfully")[0])
                    
            time.sleep(0.1)

        return (scanid,counters)
        
    def expose(self, name, empty = False, nframes=None, acq_time=None, set_empty = False):
        '''
            Perform a sequence of exposures at positions defined in self.config['pos_list'].

            Return the integrated data of the measurement with the lowest measured sample transmission.

        '''
        scan_id_list = []
        counters_list = []
        transmission_list = []
        
        for (xpos,ypos) in self.config['pos_list']:
            scanid,counters = self._expose(filename=name, xpos=xpos, ypos=ypos, empty = empty, nframes = nframes, acq_time = acq_time)
            scan_id_list.append(scanid)
            counters_list.append(counters)
            transmission_list.append(counters['transmission'])

        if not empty:
            selected_run = np.argmin(transmission_list)
        else:
            selected_run = np.argmax(transmission_list)

        self.app.logger.info(f'Selected scan #{selected_run} | {scan_id_list[selected_run]} with transmission of {transmission_list[selected_run]}.  Other options were {transmission_list}.')

        self.data['scan_ids'] = scan_id_list
        self.data['counters'] = counters_list
        self.data['transmissions'] = transmission_list
        
        if empty and set_empty:
            self.config['empty_scan_id'] = scan_id_list[selected_run]

        return self.read_integrated(scan_id_list[selected_run])

    def read_integrated(self,scanid):
        """ 
        Scans the appropriate directory for the filename of the data collected with filename
        """
        fname = f"{self.config['processed_base_path']}{scanid}{self.config['reduced_data_suffix']}"

        #check if file exists
        start_time = datetime.datetime.now()
        timeout = start_time + datetime.timedelta(seconds = self.config['file_read_timeout'])
        while not os.path.isfile(fname) and datetime.datetime.now() < timeout:
            time.sleep(0.1)
        while datetime.datetime.now() < timeout:
            try:
                with h5py.File(fname) as f:
                    I = f['processed']['result']['data'][:]
                    break
            except Exception:
                pass

        with h5py.File(fname) as f:
            I = f['processed']['result']['data'][:]
            q = f['processed']['result']['q'][:]
            err = f['processed']['result']['errors'][:]

        
        # construct an xarray with this and return it?
        data = xr.Dataset(data_vars={'I':(['position','frameid','q'],I),'dI':(['position','frameid','q'],err)},coords={'q':q})
        
        self.data['q'] = data['q'].values
        self.data.add_array('I',data['I'].values.squeeze())
        self.data.add_array('dI',data['dI'].values.squeeze())
        return scanid


_DEFAULT_CUSTOM_PORT = 5001
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
