from NistoRoboto.APIServer.driver.Driver import Driver
import pyFAI, pyFAI.azimuthalIntegrator
import numpy as np
from PIL import Image
import datetime
import fabio
import h5py,six


class ScatteringInstrument():

    def __init__(self,
                reduction_params={'poni1':0,'poni2':0,'rot1':0,'rot2':0,'rot3':0,'wavelength':1.3421e-10,'dist':2.5,'npts':500},
                detector_name='pilatus300kw',
                mask_path=None,
                ):
        self.reduction_params = reduction_params
        self.detector_name = detector_name
        self.mask_path = mask_path
        self.generateIntegrator()

    def cell_in_beam(self,cellid):

        raise NotImplementedError

    def expose(self,exposuretime,nexp):

        raise NotImplementedError

    def generateIntegrator(self):
        self.detector = pyFAI.detector_factory(name=self.detector_name)
        if(self.mask_path is None):
            self.mask=None
        else:
           self.mask = fabio.open(self.mask_path).data
        self.integrator = pyFAI.azimuthalIntegrator.AzimuthalIntegrator(detector=self.detector,
                                                                        wavelength = self.reduction_params['wavelength'],
                                                                        dist = self.reduction_params['dist'],
                                                                        poni1 = self.reduction_params['poni1'],
                                                                        poni2 = self.reduction_params['poni2'],
                                                                        rot1 = self.reduction_params['rot1'],
                                                                        rot2 = self.reduction_params['rot2'],
                                                                        rot3 = self.reduction_params['rot3'],
                                                                        )

    def setReductionParams(self,reduction_params):
        self.reduction_params.update(reduction_params)
        self.generateIntegrator()

    def setMaskPath(self,mask_path):
        self.mask_path = mask_path
        self.generateIntegrator()

    def setDetectorName(self,detector_name):
        self.detector_name=detector_name

    @Driver.unqueued()
    def getReductionParams(self):
        return self.reduction_params

    @Driver.unqueued()
    def getMaskPath(self):
        return self.mask_path

    @Driver.unqueued()
    def getDetectorName(self):
        return self.detector_name

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
                filename = self.getFilename(**filename_kwargs)
            filename1d = filename+'_r1d.csv'
            filename2d = filename+'_r2d.edf'
        else:
            filename1d = None
            filename2d = None

        if reduce_type == '1d' or write_data:
            res = self.integrator.integrate1d(img,
                self.reduction_params['npts'],
                unit='q_A^-1',
                mask=mask,
                error_model='azimuthal',
                filename=filename1d)
            if reduce_type == '1d':
                retval = np.array(res)
        if reduce_type == '2d' or write_data:
            res = self.integrator.integrate2d(img,
                self.reduction_params['npts'],
                unit='q_A^-1',
                mask=mask,
                error_model='azimuthal',
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
            f.attrs[u'creator'] = u'NistoRoboto ScatteringInstrument driver'
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
                nxinstr.create_dataset(u'temp_pyfai_calib',data=self.reduction_params)
            except:
                pass
            nxsrc = nxentry.create_group(u'source')
            nxsrc.attrs[u'NX_class'] = u'NXsource'
            nxsrc.attrs[u'canSAS_class'] = u'SASsource'
            wl = nxsrc.create_dataset(u'wavelength',data=self.reduction_params['wavelength']) #@TODO: are these units right?
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
            nxdata.attrs[u'I_axes'] = u'|Q|'
            
            Ids = nxdata.create_dataset(u'I',data=data[1])
            Ids.attrs[u'units'] = u'arbitrary'
            Ids.attrs[u'long_name'] = u'Intensity (arbitrary units)'
            Ids.attrs[u'signal'] = 1
            
            Qds = nxdata.create_dataset(u'I',data=data[0])
            Qds.attrs[u'units'] = u'arbitrary'
            Qds.attrs[u'long_name'] = u'Intensity (arbitrary units)'
            Qds.attrs[u'signal'] = 1





