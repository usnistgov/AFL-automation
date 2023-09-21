import numpy as np
import xarray as xr
import tensorflow as tf
import gpflow
from numpy.polynomial import chebyshev, legendre, polynomial
from gpflow import set_trainable
from AFL.agent import HscedGaussianProcess as HGP
from gpflow.optimizers import NaturalGradient


class Interpolator():
    def __init__(self, dataset):
        self.defaults = {}
        self.defaults['X_data_pointer'] = 'components'
        self.defaults['X_data_labels']  = 'P188' #typically the solutes components
        self.defaults['X_data_range']   = [f'{component}_range' for component in dataset.attrs['components']]
        self.defaults['Y_data_filter']  = ('SAS_savgol_xlo', 'SAS_savgol_xhi')
        self.defaults['Y_data_pointer'] = 'SAS'
        self.defaults['Y_data_coord']  = 'q'
        
        
        self.dataset = dataset
        
        #produces an N x M array N is the number of samples, M is the number of dimensions N is the number of input points
        self.X_raw = xr.DataArray(np.array([self.dataset[i].values for i in self.dataset.attrs[self.defaults['X_data_pointer']]]).T) 
        self.X_ranges = [dataset.attrs[i] for i in self.defaults['X_data_range']]
        print(self.X_ranges)
        
        #produces an N x K array N is the number of training data points, K is the number of scattering values
        self.Y_raw = self.dataset[self.defaults['Y_data_pointer']].sel({self.defaults['Y_data_coord']:slice(self.dataset.attrs[self.defaults['Y_data_filter'][0]],self.dataset.attrs[self.defaults['Y_data_filter'][1]])}).T
        
        print(self.X_raw.shape, self.Y_raw.shape)
        #construct a kernel for fitting a GP model
        self.optimizer = tf.optimizers.Adam(learning_rate=0.001)
        self.kernel = gpflow.kernels.Matern52(variance=1.0, lengthscales=(1e-1))
        self.opt_HPs = []
        
        
    def standardize_data(self):
        #####
        #if there is only one data point, there is an issue in how the X_train data standardizes. It needs to be set to a default that falls between the range. 
        #####
        
        
        #the grid of compositions does not always start at 0, this shifts the minimum
        if len(self.X_raw) > 1:
            
            self.Y_mean = [np.mean(i) for i in self.Y_raw] #this should give a mean and stdev for each q value or coefficient
            self.Y_std = [np.std(i) for i in self.Y_raw] #this should give a mean and stdev for each q value or coefficient

            #sets X_train to be from 0. to 1. along each dimension
            #should be determined based on the range of the dataset....
            self.X_train = np.array([(i - self.X_ranges[idx][0])/(self.X_ranges[idx][1] - self.X_ranges[idx][0]) for idx, i in enumerate(self.X_raw.T)]).T                           

            #sets Y_train to be within -1. to 1. for every target parameter
            self.Y_train = np.array([(i - i.mean())/i.std() for i in self.Y_raw], dtype='float64').T
            
        else:
            self.Y_mean = np.mean(self.Y_raw)
            self.Y_std = 0.
            
            self.X_train = np.array([(i - self.X_ranges[idx][0])/(self.X_ranges[idx][1] -  self.X_ranges[idx][0]) for idx, i in enumerate(self.X_raw.T)]).T
            ## the best I can do is subtract the mean of the data. If the training data are scalars, not spectra, then there will be no stdev for one point
            self.Y_train = (self.Y_raw - np.mean(self.Y_raw))
            
    def construct_model(self, kernel=None, noiseless=False, heteroscedastic=False):
        
        if kernel != None:
            self.kernel = kernel
            
        ### Due to the difficulty of doing the heteroscedastic modeling, I would avoid this for now
        if (heteroscedastic):# & (self.Y_unct!=None):
            likelihood = HGP.HeteroscedasticGaussian()
            data = (self.X_train,np.stack((self.Y_train,self.Y_unct),axis=1))
            print(data[0].shape,data[1].shape)
            self.model = gpflow.models.VGP(
                data   = data,
                kernel = kernel,
                likelihood = likelihood,
                num_latent_gps=1
                
            )
            
            self.natgrad = NaturalGradient(gamma=0.5) 
            self.adam = tf.optimizers.Adam()
            set_trainable(self.model.q_mu, False)
            set_trainable(self.model.q_sqrt, False)

        else:
            
            
            ## this is the standard GPR model
            self.model = gpflow.models.GPR(
                data   = (self.X_train,self.Y_train),
                kernel = self.kernel
            )

            ## this will force the model to go through the training points
            if noiseless:
                # print("assuming noiseless data")
                self.model.likelihood.variance = gpflow.likelihoods.Gaussian(variance=1.00001e-6).parameters[0]
                # print(self.model.parameters)
                set_trainable(self.model.likelihood.variance, False)
        
        return self.model
    
    def train_model(self,kernel=None, optimizer=None, noiseless=False, heteroscedastic=False, tol=1e-4, niter=21):
        
        if kernel != None:
            self.kernel = kernel
            
        if optimizer != None:
            self.optimizer = optimizer
        
        ## load the model if it is not there already (because it wasn't instantiated on __init__ not sure how to use isinstance() here
        if 'model' in list(self.__dict__):
            pass
        else:
            self.construct_model(kernel=kernel, noiseless=noiseless, heteroscedastic=heteroscedastic)
            
            
        
        ## optimize the model        
        # print(self.kernel,self.optimizer)
        i = 0
        break_criteria = False
        while (i <= niter) or (break_criteria==True):
        # for i in range(niter):
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
        
        return self.model
    
    def predict(self, X_new=[[0,0,0],[1,2,3]]):
        """
        Returns the simulated scattering pattern given the specified coordinates and polynomial type if reduced
        """
        if np.array(X_new).shape[1] != self.model.data[1].numpy().shape[0]:
            print("error! the coordinates requested to not match the model dimensions")

        #The coordinates being input should be in natural units. They have to be standardized to use the GP model properly
        X_new = np.array(X_new)
        
        #convert the requested X_new into standardized coordinates
        X_new = np.array([(i - self.X_ranges[idx][0])/(self.X_ranges[idx][1] - self.X_ranges[idx][0]) for idx, i in enumerate(X_new)]).T
        
        #check to see if the input coordinates and dimensions are correct:
        if np.any(X_new< 0.) or np.any(X_new> 1.):
            raise ValueError('check requested values for X_new, data not within model range')
        
        self.predictive_mean, self.predictive_variance = self.model.predict_f(X_new)
        self.predictive_mean = self.predictive_mean.numpy()
        self.predictive_variance = self.predictive_variance.numpy()
        
        
        #un-standardize
        spectra = np.array([self.predictive_mean[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_mean))])
        uncertainty_estimates = np.array([self.predictive_variance[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_variance))])
        

        return spectra, uncertainty_estimates
    
    
class ClusteredGPs():
    """
    This is the wrapper class that enables scattering interpolation within the classifier labels. 
    """
    def __init__(self, dataset=None, polytype=None):
        self.ds_manifest = dataset
        self.independentGPs = [Interpolator(dataset=dataset.where(dataset.labels == cluster).dropna(dim='sample')) for cluster in np.unique(dataset.labels)]
        
        #####
        #Note
        #####
        
        #clusters that contain one data point will not be able to interpolate. returns NaNs. not sure how to handle...
        #Suggested method is a voronoi hull to extrapolate between clustered points
        
        self.cluster_boundaries = []
        
    def train_all(self,kernel=None, optimizer=None, noiseless=True, heteroscedastic=False, niter=21, tol=1e-4):
        self.sas_models = [sg.train_model(
            kernel=kernel,
            optimizer=optimizer,
            noiseless=noiseless,
            heteroscedastic=heteroscedastic,
            niter=niter,
            tol=tol) for sg in self.sas_generators]
        
    def is_in(self, coord=None):
        """
        Returns the index corresponding to the gp model where suggested coordinates are requested
        """
        
        return idx