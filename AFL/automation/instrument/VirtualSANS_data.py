import time
import datetime
from AFL.automation.APIServer.Driver import Driver
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL
import uuid

from AFL.automation.instrument.GPInterpolator import Interpolator, ClusteredGPs
import gpflow
import tensorflow as tf
# class DummySAS(ScatteringInstrument,Driver):
class VirtualSANS_data(Driver):
    defaults = {}
    defaults['save_path'] = '/home/afl642/2305_SINQ_SANS_path'
    def __init__(self,overrides=None, clustered=False):
        '''
        Generates smoothly interpolated scattering data via a noiseless GPR from an experiments netcdf file
        '''

        self.app = None
        Driver.__init__(self,name='VirtualSANS_data',defaults=self.gather_defaults(),overrides=overrides)
        # ScatteringInstrument.__init__(self)
        if clustered:
            self.clustered=True
        self.sg = None 
        self.kernel = None
        self.optimizer = None
        self.dataset = None
        
    def set_params_dict(self,params_dict):
        self.sg.set_defaults(params_dict)
        
    def get_params_dict(self):
        return self.sg.get_defaults()
    
    def generate_model(self,alpha=0.1):
        
        if self.clustered:
            self.sg.load_datasets()
            self.sg.define_domains(alpha=alpha)
            new_gplist,union,common_idx = self.sg.unionize()
            self.sg.load_datasets(gplist=new_gplist)
        else:
            self.sg.load_data()
        
    def load_model_dataset(self,params_dict=None):
        # this class uses the information in dataset, specifically 'SAS_savgol_xlo' and 'SAS_savgol_xhi' to determine the q range
        # it also points to the 'components' attribute of the dataset to get the composition range and dimensions
        # the dataset is stored in the scattering generator object
        if self.dataset is None:
            raise ValueError("must set variable dataset in driver before load_model_dataset")
            
        # instantiate the interpolators
        if self.clustered:
            self.sg = ClusteredGPs(dataset=self.dataset)
        else:
            self.sg = Interpolator(dataset=self.dataset)        
        
        self.kernel = gpflow.kernels.Matern52(lengthscales=0.1,variance=1.)
        self.optimizer = tf.optimizers.Adam(learning_rate=0.005)

    def expose(self,name=None,exposure=None,nexp=1,block=True,write_data=True,return_data=True,measure_transmission=True,save_nexus=True):
        ## sample_data is a protected key in the self.data dictionary from Driver.py
        ## composition, which is required to reproduce scattering data, has to be a parameter in the composition dictionary
        if 'sample_composition' not in self.data:
            raise ValueError("'sample_composition' is not in self.data")
        
        ## subject to change when data structure is finalized. X must have the shape (M, D) where M is the number of evaluation points and D is the number of dimensions
        ## extra axes are squeezed out here
        ## look at isinstance
        if isinstance(self.data['sample_composition'],dict):
            X = np.array([self.data['sample_composition'][component]['values'] for component in list(self.data['sample_composition'])])
            components = list(self.data['sample_composition'])
        elif isinstance(self.data['sample_composition'],list):
            X = np.array(self.data['sample_composition'])
        else:
            print('something went wrong on import')
            X = np.array([[1.5,7]])
        
        ### predict from the model and add to the self.data dictionary

        ### scattering output is MxD where M is the number of points to evaluate the model over and D is the number of dimensions
        if self.clustered:
            if isinstance(self.sg.concat_GPs, type(None)):
                gplist = self.sg.independentGPs
            else:
                gplist = self.sg.concat_GPs
            mean, var, idx = self.sg.predict(X_new=X, gplist=gplist)
        else:
            mean, var = self.sg.predict(X_new=X)
        self.data['scattering_mu'], self.data['scattering_var'] = mean.squeeze(), var.squeeze()  
        data_pointers = self.sg.get_defaults()
        print(data_pointers['Y_data_coord'])
        if self.clustered:
            self.data[data_pointers['Y_data_coord']] = self.sg.independentGPs[0].Y_coord.values
        else:
            self.data[data_pointers['Y_data_coord']] = self.sg.Y_coord.values
        self.data['X_*'] = X
        self.data['components'] = components
        
        ### store just the predicted mean for now...
        data = self.data['scattering_mu'] 
        
        self.data['main_array'] = np.stack([self.data[data_pointers['Y_data_coord']],self.data['scattering_mu']],axis=0)
        print(self.data['main_array'].shape)

        
        ### write out the data to disk as a csv or h5?
        if write_data:
            self._writedata(data)
        


    def status(self):
        status = ['Dummy SAS data']
        return status

    def train_model(self, kernel=None, niter=1000, optimizer=None, noiseless=True, tol=1e-6, heteroscedastic=False):
        ### Hyperparameter evaluation and model "training". Can consider augmenting these in a separate call.
        if kernel != None:
            self.kernel = kernel

        if optimizer != None:
            self.optimizer = optimizer 
        
        if self.clustered:
            # print('you made it here!!!')
            # for gpmodel in self.sg.concat_GPs:
            #     print('attrs: ', list(gpmodel.__dict__))
            self.sg.train_all(
                kernel          =  self.kernel,
                niter           =  niter,
                optimizer       =  self.optimizer,
                noiseless       =  noiseless,
                tol             =  tol,
                heteroscedastic =  heteroscedastic,
                gplist          = self.sg.concat_GPs
            ) 
        else:
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
        
        
