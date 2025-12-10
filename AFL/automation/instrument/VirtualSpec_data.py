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
import lazy_loader as lazy
# Lazy load ML dependencies
gpflow = lazy.load("gpflow", require="AFL-automation[ml]")
tf = lazy.load("tensorflow", require="AFL-automation[ml]")
# class DummySAS(ScatteringInstrument,Driver):
class VirtualSpec_data(Driver):
    defaults = {}
    defaults['save_path'] = '/home/afl642/2305_SINQ_SANS_path'
    def __init__(self,overrides=None, clustered=False):
        '''
        Generates smoothly interpolated scattering data via a noiseless GPR from an experiments netcdf file
        '''

        self.app = None
        Driver.__init__(self,name='VirtualSpec_data',defaults=self.gather_defaults(),overrides=overrides)
        # ScatteringInstrument.__init__(self)
        if clustered:
            self.clustered=True
        self.sg = None 
        self.kernel = None
        self.optimizer = None
        self.dataset = None
        self.params_dict = {}
        self.len_GPs = 0
        
    def set_params_dict(self,params_dict):
        self.sg.set_defaults(params_dict)
        self.params_dict = params_dict
        
    def get_params_dict(self):
        self.params_dict = self.sg.get_defaults()
        print(self.params_dict)
        # self.params_dict = self.sg.defaults
        
    def generate_model(self,alpha=0.1):
        
        if self.clustered:
            try:
                self.sg.load_datasets()
                self.sg.define_domains(alpha=alpha)
                new_gplist,union,common_idx = self.sg.unionize()
                self.sg.load_datasets(gplist=new_gplist)
            except:
                self.sg.load_datasets()
        else:
            self.sg.load_data()
        
    def load_model_dataset(self):
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

    def measure(self,name=None,exposure=None,nexp=1,block=True,write_data=False,return_data=True,save_nexus=True):
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

            if len(X.shape) < 2:
                X = np.expand_dims(X,axis=1)
                print('correcting array dims')
                
            print('New Data point requested')
            print(X, X.shape)
        elif isinstance(self.data['sample_composition'],list):
            X = np.array(self.data['sample_composition'])
        else:
            print('something went wrong on import')
            X = np.array([[1.5,7]]).T
        
        ### predict from the model and add to the self.data dictionary
        print("X input dimeions should be D points representing the dimensionality of the space (2-many) by N columns (typically 1 point being predicted)")
        print("X input is the following ",X, X.shape,type(X))
        ### scattering output is MxD where M is the number of points to evaluate the model over and D is the number of dimensions
        if self.clustered:
            if isinstance(self.sg.concat_GPs, type(None)):
                gplist = self.sg.independentGPs
            else:
                gplist = self.sg.concat_GPs
            mean, var, idx = self.sg.predict(X_new=X, gplist=gplist)
        else:
            mean, var = self.sg.predict(X_new=X)

        # Create xarray Dataset
        ds = xr.Dataset()
        model_mu = mean.squeeze()
        model_var = var.squeeze()
        ds.attrs['model_mu'] = model_mu
        ds.attrs['model_var'] = model_var

        data_pointers = self.sg.get_defaults()
        print(data_pointers['Y_data_coord'])
        if self.clustered:
            Y_coord = self.sg.independentGPs[0].Y_coord.values
        else:
            try:
                Y_coord = self.sg.Y_coord.values
            except:
                Y_coord = None

        if Y_coord is not None:
            ds.attrs[data_pointers['Y_data_coord']] = Y_coord

        ds.attrs['X_*'] = X
        ds.attrs['components'] = components
        ds.attrs['main_array'] = model_mu
        print(ds.attrs['main_array'].shape)

        ### write out the data to disk as a csv or h5?
        if write_data:
            self._writedata(model_mu)

        return ds


    def status(self):
        status = ['Dummy SPECTROSCOPY data']
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
            print('not clustered')
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