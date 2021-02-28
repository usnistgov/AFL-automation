from NistoRoboto.APIServer.driver.Driver import Driver
import pyFAI, pyFAI.azimuthalIntegrator
import numpy as np
from PIL import Image
import datetime
import fabio


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
    def getReducedData(self,reduce_type='1d',write_data=False,filename_kwargs={},**kwargs):
        start_time = datetime.datetime.now()
        
        
        img = self.getData(**kwargs)

        got_image = datetime.datetime.now()
        
        if self.mask is None:
            mask = np.zeros(np.shape(img))
        else:
            mask = self.mask

        if write_data:
            filename = self.getFilename(**filename_kwargs)
            filename1d = filename+'_r1d.csv'
            filename2d = filename+'_r2d.edf'
        else:
            filename1d = None
            filename2d = None

        if reduce_type == '1d':
            res = self.integrator.integrate1d(img,
                self.reduction_params['npts'],
                unit='q_A^-1',
                mask=mask,
                error_model='azimuthal',
                filename=filename1d)
            res = np.array(res)
        elif reduce_type == '2d':
            res = self.integrator.integrate2d(img,
                self.reduction_params['npts'],
                unit='q_A^-1',
                mask=mask,
                error_model='azimuthal',
                filename=filename2d)    
            res = np.array(res.intensity)
        else:
            raise ValueError('unsupported return_type')
        reduced_image = datetime.datetime.now()
        
        try:
            self.app.logger.info(f'Reduced an image, image fetch took {got_image - start_time}, reduction took {reduced_image - got_image}')
        except AttributeError:
            pass
        
        return res





