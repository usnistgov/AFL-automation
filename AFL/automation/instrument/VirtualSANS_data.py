# import win32com
# import win32com.client
# from win32process import SetProcessWorkingSetSize
# from win32api import GetCurrentProcessId,OpenProcess
# from win32con import PROCESS_ALL_ACCESS
import gc
# import pythoncom
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
# from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument
# from AFL.automation.instrument.PySpecClient import PySpecClient
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL
import uuid

from AFL.automation.instrument.scatteringInterpolator import Scattering_generator
import gpflow
import tensorflow as tf
# class DummySAS(ScatteringInstrument,Driver):
class VirtualSANS_data(Driver):
    defaults = {}
    def __init__(self,overrides=None):
        '''
        Generates smoothly interpolated scattering data via a noiseless GPR from an experiments netcdf file
        '''

        self.app = None
        Driver.__init__(self,name='VirtualSANS_data',defaults=self.gather_defaults(),overrides=overrides)
        # ScatteringInstrument.__init__(self)

        self.sg = None 
        self.kernel = None
        self.optimizer = None
        self.dataset = None

    def load_model_dataset(self):
        # this class uses the information in dataset, specifically 'SAS_savgol_xlo' and 'SAS_savgol_xhi' to determine the q range
        # it also points to the 'components' attribute of the dataset to get the composition range and dimensions
        # the dataset is stored in the scattering generator object
        if self.dataset is None:
            raise ValueError("must set variable dataset in driver before load_model_dataset")
        self.sg = Scattering_generator(dataset=dataset)
        self.kernel = gpflow.kernels.Matern52(lengthscales=0.1,variance=1.)
        self.optimizer = tf.optimizers.Adam(learning_rate=0.005)

    def expose(self,name=None,exposure=None,nexp=1,block=True,write_data=True,return_data=True,measure_transmission=True,save_nexus=True):
        ## sample_data is a protected key in the self.data dictionary from Driver.py
        ## composition, which is required to reproduce scattering data, has to be a parameter in the composition dictionary
        if 'sample_composition' not in self.data:
            return ValueError("'sample_composition' is not in self.data")
        
        ## subject to change when data structure is finalized. X must have the shape (M, D) where M is the number of evaluation points and D is the number of dimensions
        ## extra axes are squeezed out here
        ## look at isinstance
        if isinstance(self.data['sample_composition'],dict):
        # if type(self.data['sample_composition']) == dict:
            X = np.array([self.data['sample_composition'][component]['values'] for component in list(self.data['sample_composition'])])
            print(X.shape, type(X))
            components = list(self.data['sample_composition'])
        elif type(self.data['sample_composition']) == list:
            X = np.array(self.data['sample_composition'])
        else:
            print('something went wrong on import')
            X = np.array([[1.5,7]])
        ## train the GP model if it has not been already
        if 'model' not in list (self.sg.__dict__):
            return ValueError("generate a model with the 'train_model' method")
        



        ### check that the units and the range of requested composition are within the dimensions of the scattering generator object

        ### predict from the model and add to the self.data dictionary
        self.data['q'] = self.sg.q

        ### scattering output is MxD where M is the number of points to evaluate the model over and D is the number of dimensions
        mean, var = self.sg.generate_SAS(coords=X)
        self.data['scattering_mu'], self.data['scattering_var'] = mean.squeeze(), var.squeeze()  
        self.data['X_*'] = X
        self.data['components'] = components
        
        ### store just the predicted mean for now...
        data = self.data['scattering_mu'] 

        
        ### write out the data to disk as a csv or h5?
        if write_data:
            self._writedata(data)
        
        if return_data:
            return self.data


    def status(self):
        status = ['Dummy SAS data']
        return status

    def train_model(self, kernel=None, niter=1000, optimizer=None, noiseless=True, tol=1e-6, heteroscedastic=False):
        ### Hyperparameter evaluation and model "training". Can consider augmenting these in a separate call.
        if kernel != None:
            self.kernel = kernel

        if optimizer != None:
            self.kernel = optimizer 
        
        
        self.sg.train_model(
            kernel          =  self.kernel,
            niter           =  niter,
            optimizer       =  self.optimizer,
            noiseless       =  noiseless,
            tol             =  tol,
            heteroscedastic =  heteroscedastic 
        )

    def _writedata(self,data):
        filename = pathlib.Path(self.config['filename'])
        filepath = pathlib.Path(self.config['filepath'])
        print(f'writing data to {filepath/filename}')
        with h5py.File(filepath/filename, 'w') as f:
            f.create_dataset(str(uuid.uuid1()), data=data)
        
        
