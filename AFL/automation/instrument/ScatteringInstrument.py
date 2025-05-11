from AFL.automation.APIServer.Driver import Driver
import lazy_loader as lazy
pyFAI = lazy.load("pyFAI", require="AFL-automation[scattering-processing]")
fabio = lazy.load("fabio", require="AFL-automation[scattering-processing]")

import numpy as np
import datetime
import h5py,six

class ScatteringInstrument():
    defaults = {}
    defaults['poni1'] = 0.0251146
    defaults['poni2'] = 0.150719
    defaults['rot1'] = 0
    defaults['rot2'] = 0
    defaults['rot3'] = 0
    defaults['wavelength'] = 1.3421e-10
    defaults['dist'] = 3.4925
    defaults['npts'] = 500
    defaults['detector_name'] = 'pilatus300kw'#set to empty for custom detector
    defaults['mask_path'] = ''

    #only used if detector_name='' (empty string)
    defaults['pixel1'] = 0.075 #pixel y size in m
    defaults['pixel2'] = 0.075 #pixel x size in m
    defaults['num_pixel1'] = 128
    defaults['num_pixel2'] = 128

    def __init__(self):
        self.generateIntegrator()

    def cell_in_beam(self,cellid):

        raise NotImplementedError

    def expose(self,exposuretime,nexp):

        raise NotImplementedError

    def generateIntegrator(self):
        if self.config['detector_name']:#if there isn't an empty string
            self.detector = pyFAI.detector_factory(name=self.config['detector_name'])
        else:
            self.detector = pyFAI.detectors.Detector(
                pixel1=self.config['pixel1'],
                pixel2=self.config['pixel2'],
                max_shape=(self.config['num_pixel1'],self.config['num_pixel2'])
            )

        if(self.config['mask_path'] is None):
            self.mask=None
        else:
           self.mask = fabio.open(self.config['mask_path']).data
        self.integrator = pyFAI.azimuthalIntegrator.AzimuthalIntegrator(
                detector=self.detector,
                wavelength = self.config['wavelength'],
                dist       = self.config['dist'],
                poni1      = self.config['poni1'],
                poni2      = self.config['poni2'],
                rot1       = self.config['rot1'],
                rot2       = self.config['rot2'],
                rot3       = self.config['rot3']
                )

    def setReductionParams(self,reduction_params):
        self.config.update(reduction_params)
        self.generateIntegrator()

    def setMaskPath(self,mask_path):
        self.config['mask_path'] = mask_path
        self.generateIntegrator()

    def setDetectorName(self,detector_name):
        self.config['detector_name']=detector_name

    @Driver.unqueued()
    def getReductionParams(self):
        params = ['poni1', 'poni2', 'rot1', 'rot2', 'rot3', 'wavelength', 'dist', 'npts']
        return {k:self.config[k] for k in params}

    @Driver.unqueued()
    def getMaskPath(self):
        return self.config['mask_path']

    @Driver.unqueued()
    def getDetectorName(self):
        return self.config['detector_name']

    @Driver.unqueued(render_hint='1d_plot',xlin=False,ylin=False,xlabel='q (A^-1)',ylabel='Intensity (AU)')
    def getReducedData(self,reduce_type='1d',write_data=False,filename=None,filename_kwargs={},**kwargs):
        start_time = datetime.datetime.now()
        
        
        img = self.getData(**kwargs)

        got_image = datetime.datetime.now()
        
        if self.mask is None:
            mask = np.zeros(np.shape(img))
        else:
            mask = self.mask

        if write_data:
            if filename is None:
                filename = self.getLastFilePath(**filename_kwargs).parts[-1]
            filename1d = filename+'_r1d.csv'
            filename2d = filename+'_r2d.edf'
        else:
            filename1d = None
            filename2d = None

        normalization_factor=1
        # normalized_sample_transmission  = self.last_measured_transmission[0]
        # open_flux = self.last_measured_transmission[1]
        # sample_flux = self.last_measured_transmission[2]
        # empty_cell_transmission = self.last_measured_transmission[3]
        # sample_transmission = normalized_sample_transmission*empty_cell_transmission
        # measurement_time  = self.getElapsedTime()
        # sample_thickness = self.config['sample_thickness']
        # calibration_factor = self.config['absolute_calibration_factor']
        # normalization_factor = (open_flux*sample_transmission*measurement_time*sample_thickness)/calibration_factor #pyFAI divides this value
        # print('getReducedData normalization calculation:')
        # print(f'sample_transmission={sample_transmission}')
        # print(f'open_flux (I0)={open_flux}')
        # print(f'measurement_time={measurement_time}')
        # print(f'sample_thickness={sample_thickness}')
        # print(f'calibration_factor={calibration_factor}')
        # print(f'normalization_factor={normalization_factor}')

        if reduce_type == '1d' or write_data:
            res = self.integrator.integrate1d(img,
                self.config['npts'],
                unit='q_A^-1',
                mask=mask,
                error_model='azimuthal',
                normalization_factor=normalization_factor,
                filename=filename1d)
            if reduce_type == '1d':
                retval = np.array(res)
        if reduce_type == '2d' or write_data:
            res = self.integrator.integrate2d(img,
                self.config['npts'],
                unit='q_A^-1',
                mask=mask,
                error_model='azimuthal',
                normalization_factor=normalization_factor,
                filename=filename2d)    
            if reduce_type == '2d':
                retval = np.array(res.intensity)
        if reduce_type != '1d' and reduce_type != '2d':
            raise ValueError('unsupported return_type')
        reduced_image = datetime.datetime.now()
        
        try:
            self.app.logger.info(f'Reduced an image, image fetch took {got_image - start_time}, reduction took {reduced_image - got_image}')
        except AttributeError:
            pass
        
        return retval

    def _writeNexus(self,data,filename,sample_name,transmission):
        timestamp = 'T'.join(str(datetime.datetime.now()))
        with h5py.File(filename+'.h5','w') as f:
            f.attrs[u'default'] = u'entry'
            f.attrs[u'file_name'] = filename
            f.attrs[u'file_time'] = timestamp
            f.attrs[u'instrument'] = self.__instrument_name__
            f.attrs[u'creator'] = u'AFL ScatteringInstrument driver'
            f.attrs[u'NeXus_version'] = u'4.3.0'
            f.attrs[u'HDF5_version'] = six.u(h5py.version.hdf5_version)
            f.attrs[u'h5py_version'] = six.u(h5py.version.version)

            nxentry = f.create_group(u'entry')
            nxentry.attrs[u'NX_class'] = u'NXentry'
            nxentry.attrs[u'canSAS_class'] = u'SASentry'
            nxentry.attrs[u'default'] = u'data'
            nxentry.create_dataset(u'title',data=filename)
            
            nxinstr = nxentry.create_group(u'instrument')
            nxinstr.attrs[u'NX_class'] = u'NXinstrument'
            nxinstr.attrs[u'canSAS_class'] = u'SASinstrument'
            try:
                nxinstr.create_dataset(u'temp_pyfai_calib',data=self.getReductionParams())
            except:
                pass
            nxsrc = nxentry.create_group(u'source')
            nxsrc.attrs[u'NX_class'] = u'NXsource'
            nxsrc.attrs[u'canSAS_class'] = u'SASsource'
            wl = nxsrc.create_dataset(u'wavelength',data=self.config['wavelength']) #@TODO: are these units right?
            wl.attrs[u'unit'] = u'm'
            nxsamp = nxentry.create_group(u'sample')
            nxsamp.attrs[u'NX_class'] = u'sample'
            nxsamp.attrs[u'canSAS_class'] = u'sample'
            
            nxsamp.create_dataset(u'name',data=sample_name)
            
            nxtrans = nxsamp.create_dataset(u'transmission',data=transmission[0])
            nxtrans.attrs[u'open_cts'] = transmission[1]
            nxtrans.attrs[u'sample_cts'] = transmission[2]
            try:
                nxtrans.attrs[u'empty_trans'] = transmission[3]
            except IndexError:
                pass
                
            nxdata = nxentry.create_group('sasdata')
            nxdata.attrs[u'NX_class'] = u'NXdata'
            nxdata.attrs[u'canSAS_class'] = u'SASdata'
            nxdata.attrs[u'signal'] = u'I'
            nxdata.attrs[u'I_axes'] = u'pix_x,pix_y'
            
            ds = nxdata.create_dataset(u'I',data=data)
            ds.attrs[u'units'] = u'arbitrary'
            ds.attrs[u'long_name'] = u'Intensity (arbitrary units)'
            ds.attrs[u'signal'] = 1
            
    def _appendReducedToNexus(self,data,filename,sample_name):
        with h5py.File(filename+'.h5','a') as f:
            nxentry = f['entry']
            
            nxdata = nxentry.create_group('sasdata_reduced')
            nxdata.attrs[u'NX_class'] = u'NXdata'
            nxdata.attrs[u'canSAS_class'] = u'SASdata'
            nxdata.attrs[u'signal'] = u'I'
            nxdata.attrs[u'I_axes'] = u'Q'
            
            Ids = nxdata.create_dataset(u'I',data=data[1])
            Ids.attrs[u'units'] = u'arbitrary'
            Ids.attrs[u'long_name'] = u'Intensity (arbitrary units)'
            Ids.attrs[u'signal'] = 1
            
            Qds = nxdata.create_dataset(u'Q',data=data[0])
            Qds.attrs[u'units'] = u'inverse angstrom'
            Qds.attrs[u'long_name'] = u'q'





