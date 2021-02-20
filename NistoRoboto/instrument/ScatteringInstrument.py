from NistoRoboto.APIServer.Driver import Driver
import pyFAI, pyFAI.azimuthalIntegrator
import numpy as np
from PIL import Image



class ScatteringInstrument():

    def __init__(self,
    			reduction_params={'poni1':0,'poni2':0,'rot1':0,'rot2':0,'rot3':0,'wavelength':0,'dist':0},
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
       	    self.mask = np.array(Image.open(mask_path))
        self.integrator = pyFAI.azimuthalIntegrator.AzimuthalIntegrator(detector=self.detector,
                                                                        wavelength = self.reduction_params['wavelength']
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
    def getReducedData(self,reduce_type='1d',**kwargs):
    	img = self.getData(**kwargs)

    	if self.mask is None:
            mask = np.zeros(np.shape(data))
        else:
            mask = self.mask

        if reduce_type == '1d':
        	res = self.integrator.integrate1d(img,self.npts,unit='q_A^-1',mask=mask,error_model='azimuthal')
        elif reduce_type == '2d':
       		res = self.integrator.integrate2d(img,self.npts,unit='q_A^-1',mask=mask,error_model='azimuthal')
        else:
        	raise ValueError('unsupported return_type')

        return res





