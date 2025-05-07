import time
import pathlib
import warnings
import json
import os
import copy
import numpy as np  # for return types in get data
import h5py  # for Nexus file writing

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument

from eic_client.EICClient import EICClient

class BioSANS(ScatteringInstrument, Driver):
    '''
    Driver for Bio-SANS instrument ORNL.
    '''
    # confirmed config parameteters
    defaults = {}
    defaults['eic_token'] = "1"
    defaults['ipts_number'] = '1234'
    defaults['beamline'] = 'CG3'
    defaults['run_cycle'] = 'RC511'
    defaults['use_subtracted_data'] = True
    defaults['config'] = 'Config0'


    def __init__(self, overrides=None):

        self.app = None
        Driver.__init__(self, name='BioSANS', defaults=self.gather_defaults(), overrides=overrides)
        ScatteringInstrument.__init__(self)

        self._client = None

        self.last_scan_id = None

        if self.config['reduced_data_dir'] is not None:
            os.chdir(self.config['reduced_data_dir'])

        self.__instrument_name__ = 'ORNL Bio-SANS instrument'

        self.status_txt = 'Just started...'
        self.last_measured_transmission = [0, 0, 0, 0]
    

    
    @property
    def client(self):
        """
        Property that returns the EIC client instance.
        
        If the client doesn't exist yet, it instantiates a new EICClient
        using the token and beamline from the configuration.
        
        Returns
        -------
        EICClient
            The client instance for communicating with the instrument.
        """
        if self._client is None:
            self._client = EICClient(
                ipts_number=self.config['ipts_number'],
                eic_token=self.config['eic_token'],
                beamline=self.config['beamline']
            )
        return self._client
    
    def reset_client(self):
        '''
        Reset the EICClient instance
        '''
        self._client = None
    
    def lastMeasuredTransmission(self):
        return self.last_measured_transmission

    @Driver.unqueued()
    def getLastReductionLogFilePath(self, **kwargs):
        """ get the currently set file name """
        data_path = '/HFIR/{INST}/IPTS-{IPTS}/shared/autoreduce/RC-{RUN_CYCLE}/{CONFIG}' #path

        path = pathlib.Path(
            data_path.format(
                INST=self.config['beamline'],
                IPTS=self.config['ipts_number'], 
                RUN_CYCLE=self.config['run_cylce'], 
                CONFIG=self.config['config']
                )
                )

        run_number = self.getLastRunNumber()
        filename = f'r{run_number:d}_{run_number:d}_reduction_log.hdf'
        filepath = pathlib.Path(path) / filename
        return filepath

    def _readLastTransmission(self):
        filepath = self.getLastReductionLogFilePath()
        with h5py.File(filepath, 'r') as h5:
            transmission = h5['reduction_information']['special_parameters']['sample_transmission']['main']['value'][()]
        return transmission

    @Driver.unqueued()
    def getLastTransmission(self, **kwargs):
        return self.readFileSafely(self._readLastTransmission)


    def setExposure(self, exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.config['exposure'] = exposure

    @Driver.unqueued()
    def getLastFilePath(self, **kwargs):
        """ get the currently set file name """
        data_path = '/HFIR/{INST}/IPTS-{IPTS}/shared/autoreduce/RC-{RUN_CYCLE}/{CONFIG}/1D' #path

        path = pathlib.Path(
            data_path.format(
                INST=self.config['beamline'],
                IPTS=self.config['ipts_number'], 
                RUN_CYCLE=self.config['run_cylce'], 
                CONFIG=self.config['config']
                )
                )

        run_number = self.getLastRunNumber()
        filename = f'r{run_number:d}_{run_number:d}_1D_combined.txt'
        filepath = pathlib.Path(path) / filename
        return filepath


    def _readLastReducedFile(self):
        filepath = self.getLastFilePath()
        q, I, dI, dQ = np.loadtxt(filepath, skiprows=2).T

        return {'q': q, 'I': I, 'dI': dI, 'dQ': dQ}

    @Driver.unqueued(render_hint='2d_img', log_image=True)
    def readFileSafely(self, file_read_function, **kwargs):
        try:
            data = file_read_function()
        except (FileNotFoundError, OSError, KeyError):
            nattempts = 1
            while nattempts < 31:
                nattempts = nattempts + 1
                time.sleep(1.0)
                try:
                    data = file_read_function()
                except (FileNotFoundError, OSError, KeyError):
                    if nattempts == 30:
                        raise FileNotFoundError(f'Could not locate file after {nattempts} tries')
                    else:
                        warnings.warn(f'Failed to load file, trying again, this is try {nattempts}')
                else:
                    break

        return data

    def _validateExposureType(self, exposure_type):
        if exposure_type not in ['time']:
            raise ValueError(f'Exposure type must be one of "time", not {exposure_type}')

    def blockForTableScan(self):
        status_sucess,  is_done, state, status_response_data = self.client.get_scan_status(self.last_scan_id)

        loop_count = 0
        while not is_done:
            time.sleep(0.1)
            status_sucess,  is_done, state, status_response_data = self.client.get_scan_status(self.last_scan_id)
            loop_count += 1


    def _simple_expose(self, exposure, name=None, block=False, exposure_type='time', tmax=1800):
        """
        Perform a simple exposure with the specified parameters.

        This method sets up and performs an exposure of the sample, optionally blocking until the exposure is complete.

        Parameters
        ----------
        exposure : float
            The exposure time or counts.
        name : str, optional
            The name of the sample (default is None).
        block : bool, optional
            If True, block until the exposure is complete (default is False).
        exposure_type : str, optional
            The type of exposure, must be one of 'time', 'detector', or 'monitor' (default is 'detector').
        tmax : int, optional
            The maximum time to wait for the exposure in seconds (default is 1800). This is only applicable for the
            exposure_type 'detector'.

        Raises
        ------
        ValueError
            If the exposure type is not one of 'time', 'detector', or 'monitor'.
        """
        self._validateExposureType(exposure_type)

        self.setExposure(exposure)

        self.status_txt = f'Starting {exposure} count table scan named {name}'
        if self.app is not None:
            self.app.logger.debug(self.status_txt)

        params = {
            'run_mode': 0, #????
            'desc': 'AFL submitted table scan'
        }

        if exposure_type == 'time':
            success, self.last_scan_id,response_data = self.client.submit_table_scan(
                parms={
                    'run_mode': 0, #????
                    'headers': ['Title','Wait For','Value'],
                    'rows': [[name, 'seconds', exposure]]
                },
                desc=f'AFL submitted table scan named {name}',
                simulate_only=False,
            )
        elif exposure_type == 'monitor':
            raise NotImplementedError('Monitor exposure is not implemented for BioSANS')
        elif exposure_type == 'detector':
            raise NotImplementedError('Monitor exposure is not implemented for BioSANS')

        if block:
            self.blockForTableScan()

    @Driver.quickbar(qb={'button_text': 'Expose',
                         'params': {
                             'name': {'label': 'Name', 'type': 'text', 'default': 'test_exposure'},
                             'exposure': {'label': 'Exposure (s)', 'type': 'float', 'default': 5},
                             'reduce_data': {'label': 'Reduce?', 'type': 'bool', 'default': True},
                             'measure_transmission': {'label': 'Measure Trans?', 'type': 'bool', 'default': True}
                         }})
    def expose(self, name=None, exposure=None, block=True,
               save_reduced_data=True, save_nexus=True, exposure_type='detector'):
        """
        Perform an exposure with the specified parameters.

        This method performs an exposure of the sample, optionally measuring the transmission, reducing the data,
        and saving it in Nexus format.

        Parameters
        ----------
        name : str, optional
            The name of the sample (default is None).
        exposure : float, optional
            The exposure time or counts (default is None).
        block : bool, optional
            If True, block until the exposure is complete (default is True).
        save_nexus : bool, optional
            If True, save the data in Nexus format (default is True).
        exposure_type : str, optional
            The type of exposure, must be one of 'time', 'detector', or 'monitor' (default is 'detector').

        Raises
        ------
        ValueError
            If the exposure type is not one of 'time', 'detector', or 'monitor'.
        FileNotFoundError
            If the data file cannot be located after multiple attempts.

        """
        self._validateExposureType(exposure_type)

        self._simple_expose(exposure=exposure, exposure_type=exposure_type, block=block)
        time.sleep(15)

        if self.data is not None:
            data = self.readFileSafely(self._readLastReducedFile)
            transmission = self.readFileSafely(self._readLastTransmission)

            self.data.add_array('I',data['I'])
            self.data.add_array('dI',data['dI'])
            self.data.add_array('dQ',data['dQ'])
            self.data.add_array('q',data['q'])
            self.data['q'] = data['q']
            self.data['sample_transmission'] = transmission


        self.status_txt = 'Instrument Idle'


    def status(self):
        status = []
        status.append(
            f'Last Measured Transmission: scaled={self.last_measured_transmission[0]} using empty cell trans of {self.last_measured_transmission[3]} with {self.last_measured_transmission[1]} raw counts in open {self.last_measured_transmission[2]} sample')
        status.append(f'Status: {self.status_txt}')
        return status


_DEFAULT_PORT=5001

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
