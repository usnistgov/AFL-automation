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

from EICClient import EICClient

class BioSANS(ScatteringInstrument, Driver):
    '''
    Driver for Bio-SANS instrument ORNL.
    '''
    # confirmed config parameteters
    defaults = {}
    defaults['eic_token'] = 1
    defaults['ipts_number'] = 1234
    defaults['beamline'] = 1
    defaults['run_cycle'] = 1
    defaults['use_subtracted_data'] = True
    defaults['data_path'] = '/HFIR/CG3/IPTS-{IPTS}/shared/autoreduce/RC-{RUN_CYCLE}/Config{CONFIG_NUMBER}/1D' #path

    # unconfirmed config parameteters
    defaults['empty transmission'] = 1
    defaults['transmission strategy'] = 'sum'
    defaults['reduced_data_dir'] = ''
    defaults['exposure'] = 1.
    defaults['absolute_calibration_factor'] = 1

    defaults['pixel1'] = 0.075  # pixel y size in m
    defaults['pixel2'] = 0.075  # pixel x size in m
    defaults['num_pixel1'] = 128
    defaults['num_pixel2'] = 128
    defaults['transmission_box_radius_x'] = 20
    defaults['transmission_box_radius_y'] = 20

    defaults['beamstop_in'] = -70 #bsy
    defaults['beamstop_out'] = -200 #bsy

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
    def getLastFilePath(self, **kwargs):
        """ get the currently set file name """

        path = pathlib.Path(self.config['data_path'].format(IPTS=self.config['ipts_number'], RUN_CYCLE=self.config['run_cylce'], CONFIG_NUMBER=0))
        if self.config['use_subtracted_data']:
            path = path / 'Subtracted'
        filename = f'CG3_{self.getLastRunNumber():d}.nxs.h5' #need the file type and format, 
        filepath = pathlib.Path(path) / filename

        if self.app is not None:
            self.app.logger.debug(f'Last file determined to be to be {filepath}')
        else:
            print(f'Last file found to be {filepath}')
        return filepath

    def setExposure(self, exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.config['exposure'] = exposure


    def readH5(self, filepath):
        raise NotImplementedError('readH5 is not implemented for BioSANS')
        # TODO: Need to get filetype and format from BioSANS team

        out_dict = {}
        with h5py.File(filepath, 'r') as h5:
            out_dict['counts'] = h5['entry1/data1/counts'][()]

        # NICOS makes partially written files, this is a workaround
        if np.sum(out_dict['counts'])<1e-6:
            raise FileNotFoundError

        return out_dict

    @Driver.unqueued(render_hint='2d_img', log_image=True)
    def getData(self, **kwargs):
        try:
            filepath = self.getLastFilePath()
            data = self.readH5(filepath)['counts']
        except (FileNotFoundError, OSError, KeyError):
            nattempts = 1
            while nattempts < 31:
                nattempts = nattempts + 1
                time.sleep(1.0)
                filepath = self.getLastFilePath()
                try:
                    data = self.readH5(filepath)['counts']
                except (FileNotFoundError, OSError, KeyError):
                    if nattempts == 30:
                        raise FileNotFoundError(f'Could not locate file {filepath} after {nattempts} tries')
                    else:
                        warnings.warn(f'Failed to load file {filepath}, trying again, this is try {nattempts}')
                else:
                    break

        return np.nan_to_num(data)

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

    @Driver.quickbar(qb={'button_text': 'Measure Transmission',
                         'params': {
                             'set_empty_transmission': {'label': 'Set Empty Trans?', 'type': 'boolean',
                                                        'default': False}
                         }})
    def measureTransmission(self, exposure=1e5, exposure_type='detector', set_empty_transmission=False,
                            return_full=False):
        """
        Measure the transmission of the sample.

        This method measures the transmission of the sample by performing a series of commands to move the beamstop,
        open the shutter, and expose the sample. The transmission is calculated based on the counts from the detector
        and the normalization monitor.

        Parameters
        ----------
        exposure : float, optional
            The exposure time or counts (default is 1e5).
        exposure_type : str, optional
            The type of exposure, must be one of 'time', 'detector', or 'monitor' (default is 'detector').
        set_empty_transmission : bool, optional
            If True, set the measured transmission as the empty transmission (default is False).
        return_full : bool, optional
            If True, return the full transmission data including raw counts and empty transmission (default is False).

        Returns
        -------
        float or tuple
            The measured transmission. If `return_full` is True, returns a tuple containing the scaled transmission,
            monitor counts, sample counts, and empty transmission.

        Notes
        -----
        This method performs the following steps:
        1. Close the shutter and move the beamstop out.
        2. Open the shutter and expose the sample.
        3. Close the shutter and move the beamstop back in.
        4. Calculate the transmission based on the counts from the detector and the normalization monitor.
        5. Optionally set the measured transmission as the empty transmission.
        6. Return the measured transmission or the full transmission data.
        """
        raise NotImplementedError('Measure Transmission is not implemented for BioSANS')
        # TODO: Need to figure out how transmissions are measureed for BioSANS

        self._validateExposureType(exposure_type)

        self.client.command(f'maw(shutter,"closed")')
        self.client.command(f'move(att,"1")') #move attenuator to 1
        self.client.command(f'move(bsy,{self.config["beamstop_out"]})')
        self.client.command(f'wait()')
        self.client.command(f'maw(shutter,"open")')

        self._simple_expose(exposure=exposure, exposure_type=exposure_type, block=True)

        self.client.command(f'maw(shutter,"closed")')
        self.client.command(f'move(bsy,{self.config["beamstop_in"]})')
        self.client.command(f'move(att,"0")')
        self.client.command(f'wait()')
        self.client.command(f'maw(shutter,"open")')

        # convert PONI to pixels.
        # XXX Needs to be shifted into Python index coords???
        xcenter = int(self.config['poni2']/self.config['pixel2'])
        ycenter = int(self.config['poni1']/self.config['pixel1'])

        # calculate bounds of integration box
        xlo = int(xcenter - self.config['transmission_box_radius_x'])
        xhi = int(xcenter + self.config['transmission_box_radius_x'])
        ylo = int(ycenter - self.config['transmission_box_radius_y'])
        yhi = int(ycenter + self.config['transmission_box_radius_y'])

        # make sure x and y bounds are within detector size
        xhi = int(min(xhi,self.config['num_pixel2']-1))
        yhi = int(min(yhi,self.config['num_pixel1']-1))
        xlo = int(max(xlo,0))
        ylo = int(max(ylo,0))

        cts = self.banana(xlo=xlo,xhi=xhi,ylo=ylo,yhi=yhi,measure=False)

        monitor_cts = self.client.get(self.config['normalization_monitor'])
        monitor_cts = monitor_cts[self.config['normalization_monitor_index']]

        try:
            trans = cts / monitor_cts #!!! add dead_time correction to monitor
        except ZeroDivisionError:
            trans = -1
        
        if np.isnan(trans):
            trans = -1

        if set_empty_transmission:
            self.config['empty transmission'] = trans

        self.last_measured_transmission = (
            trans / self.config['empty transmission'],
            monitor_cts,
            cts,
            self.config['empty transmission']
        )

        if return_full:
            return self.last_measured_transmission
        else:
            return trans / self.config['empty transmission']


    @Driver.quickbar(qb={'button_text': 'Expose',
                         'params': {
                             'name': {'label': 'Name', 'type': 'text', 'default': 'test_exposure'},
                             'exposure': {'label': 'Exposure (s)', 'type': 'float', 'default': 5},
                             'reduce_data': {'label': 'Reduce?', 'type': 'bool', 'default': True},
                             'measure_transmission': {'label': 'Measure Trans?', 'type': 'bool', 'default': True}
                         }})
    def expose(self, name=None, exposure=None, exposure_transmission=None, block=True, reduce_data=True,
               measure_transmission=True,
               save_nexus=True, exposure_type='detector'):
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
        exposure_transmission : float, optional
            The exposure time or counts for transmission measurement (default is None).
        block : bool, optional
            If True, block until the exposure is complete (default is True).
        reduce_data : bool, optional
            If True, reduce the data after exposure (default is True).
        measure_transmission : bool, optional
            If True, measure the transmission before exposure (default is True).
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

        if measure_transmission:
            self.measureTransmission(exposure=exposure_transmission,exposure_type=exposure_type)

        self._simple_expose(exposure=exposure, exposure_type=exposure_type, block=block)
        time.sleep(15)

        if reduce_data or save_nexus:
            raise NotImplementedError('Expose is not implemented for BioSANS')
            # TODO: Need to figure out how to reduce data for BioSANS

            data = self.getData()
            print(f"Loaded data with {data.sum()} total counts")
            if save_nexus:
                self.status_txt = 'Writing Nexus'
                normalized_sample_transmission = self.last_measured_transmission[0]
                if self.data is not None:
                    self.data.add_array('raw',data)
                    self.data['normalized_sample_transmission'] = normalized_sample_transmission
                self._writeNexus(data, name, name, self.last_measured_transmission)

            if reduce_data:
                self.status_txt = 'Reducing Data'
                reduced = self.getReducedData(write_data=True, filename=name)
                if self.data is not None:
                    self.data['q'] = reduced[0]
                    self.data.add_array('I', reduced[1])
                    self.data.add_array('dI', reduced[2])
                np.savetxt(f'{name}_chosen_r1d.csv', np.transpose(reduced), delimiter=',')

                normalized_sample_transmission = self.last_measured_transmission[0]
                open_flux = self.last_measured_transmission[1]
                sample_flux = self.last_measured_transmission[2]
                empty_cell_transmission = self.last_measured_transmission[3]
                sample_transmission = normalized_sample_transmission * empty_cell_transmission

                if self.data is not None:
                    self.data['normalized_sample_transmission'] = normalized_sample_transmission
                    self.data['open_flux'] = open_flux
                    self.data['sample_flux'] = sample_flux
                    self.data['empty_cell_transmission'] = empty_cell_transmission
                    self.data['sample_transmission'] = sample_transmission

                    # for sample server
                    self.data['transmission'] = normalized_sample_transmission

                if save_nexus:
                    self._appendReducedToNexus(reduced, name, name)

                out = {}
                out['normalized_sample_transmission'] = normalized_sample_transmission
                out['open_flux']                      = open_flux
                out['sample_flux']                    = sample_flux
                out['empty_cell_transmission']        = empty_cell_transmission
                out['sample_transmission'] = sample_transmission

                out = {k:float(v) for k,v in out.items()}
                with open(pathlib.Path(self.config['reduced_data_dir'])/f'{name}_trans.json', 'w') as f:
                    json.dump(out, f)

            self.status_txt = 'Instrument Idle'


    def banana(self,xlo=40,xhi=80,ylo=40,yhi=80,measure=True):
        """ Calculate a sum of data over a pixel range """
        raise NotImplementedError('banana is not implemented for BioSANS')
        # TODO: Need to figure out how to get the data for BioSANS

        if measure:
            self.client.command('count(m=1e3)')
            self.blockForTableScan()
        arrays = self.client.livedata[self.config['detector']+'_live'] #return arrays from all detectors
        array  = arrays[self.config['detector_index']] #return selected detector array
        counts = array[ylo:yhi,xlo:xhi].sum()
        return counts

    def status(self):
        status = []
        status.append(
            f'Last Measured Transmission: scaled={self.last_measured_transmission[0]} using empty cell trans of {self.last_measured_transmission[3]} with {self.last_measured_transmission[1]} raw counts in open {self.last_measured_transmission[2]} sample')
        status.append(f'Status: {self.status_txt}')
        status.append(f'<a href="getData" target="_blank">Live Data (2D)</a>')
        status.append(f'<a href="getReducedData" target="_blank">Live Data (1D)</a>')
        status.append(f'<a href="getReducedData?render_hint=2d_img&reduce_type=2d">Live Data (2D, reduced)</a>')
        return status


_DEFAULT_PORT=5001

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
