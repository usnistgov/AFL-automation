from AFL.automation.APIServer.Driver import Driver
#from AFL.automation.instrument.Instrument import Instrument
import numpy as np # for return types in get data
import seabreeze
import time
import datetime
import h5py
from pathlib import Path
import uuid
import pathlib
import copy
import warnings

from typing import Optional

try:
    from tiled.queries import Eq
except ImportError:
    warnings.warn("Cannot import from tiled...reduction will not work",stacklevel=2)


class SeabreezeUVVis(Driver):
    defaults = {}
    defaults['correctDarkCounts'] = False
    defaults['correctNonlinearity'] = False
    defaults['exposure'] = 0.010
    defaults['exposure_delay'] = 0
    defaults['saveSingleScan'] = False
    defaults['filename'] = 'test.h5'
    defaults['filepath'] = '.' 
    defaults['reference_uuid'] = '.' #variable name in tiled
    defaults['air_uuid'] = '.' #variable name in tiled

    def __init__(self,backend='cseabreeze', device_serial=None,overrides=None):
        self.app = None
        self.name = 'SeabreezeUVVis'
        Driver.__init__(self,name='SeabreezeUVVis',defaults = self.gather_defaults(),overrides=overrides)
        print(f'configuring Seabreeze using backend {backend}')
        seabreeze.use(backend)
        from seabreeze.spectrometers import Spectrometer,list_devices
        print(f'attempting to list spectrometers...')
        print(f'seabreeze sees devices: {list_devices()}')
        if device_serial is None:
            print(f'Connecting to first available...')
            self.spectrometer = Spectrometer.from_first_available()
        else:
            print(f'Connecting to fixed serial, {device_serial}')
            self.spectrometer = Spectrometer.from_serial_number(device_serial)
        print(f'Connected successfully, to a {self.spectrometer}')

        self.wl = self.spectrometer.wavelengths()

        self.setExposure(self.config['exposure'])


    @Driver.unqueued()
    def getExposure(self):
        return self.config['exposure']

    @Driver.unqueued()
    def getExposureDelay(self):
        return self.config['exposure_delay']

    @Driver.unqueued()
    def getFilename(self):
        return self.config['filename']

    @Driver.unqueued()
    def getSaveSingleScan(self):
        return self.config['saveSingleScan']

    @Driver.unqueued()
    def getFilepath(self):
        return self.config['filepath']

    def setFilepath(self,filepath):
        self.config['filepath'] = Path(filepath)

    def setFilename(self,filename):
        self.config['filename'] = filename

    def setSaveSingleScan(self,saveSingleScan):
        self.config['saveSingleScan'] = saveSingleScan

    def setExposureDelay(self,time):
        self.config['exposure_delay'] = time

    def setExposure(self,time):
        self.config['exposure'] = time
        self.spectrometer.integration_time_micros(1e6*time)

    def collectContinuous(self,duration,start=None,return_data=False,**kwargs):
        warnings.warn('collectContinuous should be replaced with collect', DeprecationWarning, stacklevel=2)

        data = []
        duration = datetime.timedelta(seconds=duration)

        if start is None:
            start = datetime.datetime.now()

        #print(start)
        #print(datetime.timedelta(0,duration))
        while datetime.datetime.now() < start:
            pass

        while datetime.datetime.now() < (start + duration):
            data.append(self.spectrometer.intensities(
                        correct_dark_counts=self.config['correctDarkCounts'], 
                        correct_nonlinearity=self.config['correctNonlinearity']))
            time.sleep(self.config['exposure_delay'])
        
        if self.data is not None:
            self.data['mode'] = 'continuous'
            self.data['wavelength'] = self.wl.tolist()
            self.data.add_array('wavelength',self.wl.tolist())
            self.data.add_array('spectra',data[0])
           
        self._writedata(data)

        if not return_data:
            data = f'data written to file: {self.config["filename"]}'
            return data
        else:
            return data


    @Driver.unqueued()
    def collectSingleSpectrum(self, set_reference=False, set_air=False, **kwargs):
        warnings.warn('collectSingleSpectrum should be replaced with collect', DeprecationWarning, stacklevel=2)

        wl = self.wl[1:]
        raw_data = self.spectrometer.intensities( 
                correct_dark_counts=self.config['correctDarkCounts'], 
                correct_nonlinearity=self.config['correctNonlinearity']
                )
        raw_data = raw_data[1:]
                

        if self.config['saveSingleScan']:
            self._writedata(raw_data)

        if set_reference:
            self.config['reference_uuid'] = copy.deepcopy(self.data['sample_uuid'])

        if set_air:
            self.config['air_uuid'] = copy.deepcopy(self.data['sample_uuid'])
        

        if self.data is not None:
            self.data['mode'] = 'single'
            self.data['wavelength'] = wl
            self.data['reduced'] = False
            self.data.add_array('wavelength',wl)
            self.data.add_array('spectrum_raw',raw_data)


    def _writedata(self,data):
        filepath = pathlib.Path(self.config['filepath'])
        filename = pathlib.Path(self.config['filename'])
        data = np.array([self.wl,data])
        with h5py.File(filepath/filename, 'w') as f:
            dset = f.create_dataset(str(uuid.uuid1()), data=data)

    def collect(
        self,
        nframes: int,
        reduced: bool= False,
        absorbance: bool=True,
        set_reference: bool =False,
        set_air: bool=False,
        exposure: Optional[float] = None,
        **kwargs
        ):

        if exposure is not None:
            self.setExposure(exposure)

        wl = self.wl[1:] # remove internal dark reference 
        data_raw = []
        for frame in range(nframes):
           I = self.spectrometer.intensities( 
                   correct_dark_counts=self.config['correctDarkCounts'], 
                   correct_nonlinearity=self.config['correctNonlinearity']
           )
           I = I[1:] # remove internal dark reference
           data_raw.append(I)
           time.sleep(self.config['exposure_delay'])

        data_raw_mean = np.mean(data_raw,axis=0)
        data_raw_std = np.std(data_raw,axis=0)

        if reduced:
            data_mean, data_std = self.reduced(data_raw_mean, data_raw_std, absorbance=absorbance)

        if self.config['saveSingleScan']:
            self._writedata(data_raw)

        if set_reference:
            self.config['reference_uuid'] = copy.deepcopy(self.data['sample_uuid'])

        if set_air:
            self.config['air_uuid'] = copy.deepcopy(self.data['sample_uuid'])
        
        if self.data is not None:
            self.data['mode'] = 'collect'
            self.data['wavelength'] = wl
            self.data['reference_uuid'] = self.config['reference_uuid']
            self.data['air_uuid'] = self.config['air_uuid']
            self.data['reduced'] = reduced
            self.data['absorbance'] = absorbance
            self.data.add_array('wavelength',wl)
            self.data.add_array('all_spectra',data_raw)
            self.data.add_array('spectrum_raw',data_raw_mean)
            self.data.add_array('spectrum_raw_std',data_raw_std)
            if reduced:
                self.data.add_array('spectrum',data_mean)
                self.data.add_array('spectrum_std',data_std)

        if reduced:
            data_out = [wl.tolist(),data_mean.tolist()] 
        else:
            data_out = [wl.tolist(),data_raw_mean.tolist()] 

        return data_out

    def reduced(self,data_raw_mean,data_raw_std,absorbance=True):
        if self.data is None:
            raise ValueError("Cannot reduce without DataTiled...please set tiled parameters in server_script")

        tiled_result = self.data.tiled_client.search(Eq('sample_uuid',self.config['reference_uuid']))
        if len(tiled_result)==0:
            raise ValueError(f"Can't reduce! Could not find tiled entry for measurement sample_uuid={self.config['reference_uuid']}")

        ref_spectrum = tiled_result.search(Eq('array_name','spectrum_raw')).items()[-1][-1][()] #grabs the last entry that matches
        ref_spectrum_std = tiled_result.search(Eq('array_name','spectrum_raw_std')).items()[-1][-1][()]

        data_mean = data_raw_mean/ref_spectrum
        data_std = data_mean*(data_raw_std/np.abs(data_raw_mean) + ref_spectrum_std/np.abs(ref_spectrum_std))

        if absorbance:
            data_mean = 1.0 - data_mean

        return data_mean,data_std


