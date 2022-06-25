from AFL.automation.APIServer.driver.Driver import Driver
#from AFL.automation.instrument.Instrument import Instrument
import numpy as np # for return types in get data
import seabreeze
import time
import datetime
import h5py
from pathlib import Path
import uuid


class SeabreezeUVVis(Driver):

    def __init__(self,backend='cseabreeze',device_serial=None):
        self.app = None
        self.name = 'SeabreezeUVVis'
        
        self.config = {}
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
        self.config['correctDarkCounts'] = False
        self.config['correctNonlinearity'] = False
        self.config['exposure'] = 0.010
        self.config['exposure_delay'] = 0
        self.config['saveSingleScan'] = False
        self.config['filename'] = 'test.h5'
        self.config['filepath'] = Path('.')

        self.wl = self.spectrometer.wavelengths()

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

    def collectContinuous(self,duration,start=None,return_data=False):
        data = []

        if start is None:
            start = datetime.datetime.now()
        while datetime.datetime.now() < start:
            pass

        while datetime.datetime.now() < (start + duration):
            data.append([self.wl,self.spectrometer.intensities(correct_dark_counts=self.config['correctDarkCounts'], 
                    correct_nonlinearity=self.config['correctNonlinearity'])])
            time.sleep(self.config['exposure_delay'])

        self._writedata(data)

        if not ret:
            data = f'data written to file: {self.filename}'

        return data

    @Driver.unqueued()
    def collectSingleSpectrum(self):
        data = [self.wl,self.spectrometer.intensities(
            correct_dark_counts=self.config['correctDarkCounts'], 
                    correct_nonlinearity=self.config['correctNonlinearity'])]

        if self.config['saveSingleScan']:
            self._writedata(data)

        return data

    def _writedata(self,data):
        data = np.array(data)
        with h5py.File(self.config['filepath']/self.config['filename'], 'w') as f:
            dset = f.create_dataset(str(uuid.uuid1()), data=data)



