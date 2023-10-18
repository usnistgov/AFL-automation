import time
import datetime
from AFL.automation.APIServer.Driver import Driver
import numpy as np # for return types in get data
import h5py #for Nexus file writing
import os
import pathlib
import PIL
import uuid

import gpflow
from gpflow import set_trainable
import tensorflow as tf

class VirtualSpec_data(Driver):
    defaults = {}
    def __init__(self,overrides=None):
        '''
        Generates smoothly interpolated spectroscopy data via a noiseless GPR from an experiments netcdf file
        '''

        self.app = None
        Driver.__init__(self,name='VirtualSpec_data',defaults=self.gather_defaults(),overrides=overrides)
        # ScatteringInstrument.__init__(self)

        self.dataset = None
        self.kernel = None
        self.optimizer = None
        self.camera = None
        self.turb_model = None

    def load_model_dataset(self):
        if self.dataset is None:
            raise ValueError("must set variable dataset in driver before load_model_dataset")

        self.kernel = gpflow.kernels.Matern52(lengthscales=0.1,variance=1.)
        self.optimizer = tf.optimizers.Adam(learning_rate=0.005)


    def generate_synthetic_data(self,inputs=[(0,15,25),(0,15,25)], datafxn=None,  **kwargs):
        '''
        inputs: list of tuples [(x1_lo, x1_hi,n_x1),(x2_lo,x2_hi,n_x2),...,(xi_lo,xi_hi,n_xi)]
        datafx: function that takes in the x data and returns some target to train off of
        '''
        components = [np.linspace(lo, hi, n) for lo, hi, n in inputs]
        norm_components = [(c - min(c))/max(c - min(c)) for c in components]

        X_train = np.meshgrid(components) #will produce matrices (n_x1 by n_x2 by ... n_xi)
        self.X_train = np.array([i.ravel() for i in X_train]).T #shapes the input array for the model NxD

        self.Y_train = datafxn(self.X_train) #should produce an NxM array M >= 1
        if len(self.Y_train.shape) == 1:
            self.Y_train = np.expand_dims(self.Y_train, axis=1)
        
        #standardize the Y_train data
        self.Y_train_norm = np.array([(i - np.mean(i))/np.std(i) for i in Y_train.T]).T

        #instantiate the GPR kernel and optimizer 
        self.kernel = gpflow.kernels.Matern52(lengthscales=0.1,variance=1.)
        self.optimizer = tf.optimizers.Adam(learning_rate=0.005)
        
    def measure(self,write_data=False,return_data=False):
        ## sample_data is a protected key in the self.data dictionary from Driver.py
        ## composition, which is required to reproduce scattering data, has to be a parameter in the composition dictionary
        if 'sample_composition' not in self.data:
            raise ValueError("'sample_composition' is not in self.data")
        
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
        if self.model is not None:
            raise ValueError("generate a model with the 'train_model' method")
        



        ### predict from the model and add to the self.data dictionary
        mean, var = self.model.predictf(X)
        self.data['spec_mu'], self.data['spec_var'] = mean.squeeze(), var.squeeze()
        self.data['X_*'] = X
        self.data['components'] = components
        
        data = self.data['spec_mu']

        ### write out the data to disk as a csv or h5?
        if write_data:
            self._writedata(data)
        
        if return_data:
            return turbidity_metric, [0.,0.]

    def status(self):
        status = ['Dummy SAS data']
        return status

    def train_model(self, kernel=None, niter=1000, optimizer=None, noiseless=True, tol=1e-6, heteroscedastic=False):
        ### Hyperparameter evaluation and model "training"
        #specify the kernel and optimizer if not already
        if kernel != None:
            self.kernel = kernel

        if optimizer != None:
            self.kernel = optimizer 
        

        ## instantiate the GPR model
        self.model = gpflow.models.GPR(
            data=(self.X_train, self.Y_train),
            kernel=self.kernel,
            noise_variance=1.0
        )


        ## set the appropriate noiseless parameter
        if noiseless:
            self.model.likelihood.variance = gpflow.lieklihoods.Gaussian(variance=1.0001e-6).parameter[0]
            set_trainable(self.model.likelihood.variance, False)
        

        #train the model to a threshold or to a specified number of iterations
        i = 0
        break_criteria = False
        while (i <= niter) or (break_criteria==True):
            if heteroscedastic == False:
                pre_step_HPs = np.array([i.numpy() for i in self.model.parameters])
                self.optimizer.minimize(self.model.training_loss, self.model.trainable_variables)
                self.opt_HPs.append([i.numpy() for i in self.model.parameters])
                post_step_HPs = np.array([i.numpy() for i in self.model.parameters])
                i+=1
                if all(abs(pre_step_HPs-post_step_HPs) <= tol):
                    break_criteria=True
                    break
            else:
                self.natgrad.minimize(self.model.training_loss, [(self.model.q_mu, self.model.q_sqrt)])
                self.adam.minimize(self.model.training_loss, self.model.trainable_variables)
                i+=1 


        
    def _writedata(self,data):
        filename = pathlib.Path(self.config['filename'])
        filepath = pathlib.Path(self.config['filepath'])
        print(f'writing data to {filepath/filename}')
        with h5py.File(filepath/filename, 'w') as f:
            f.create_dataset(str(uuid.uuid1()), data=data)
        
        
