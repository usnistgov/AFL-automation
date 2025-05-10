import numpy as np
import xarray as xr
import lazy_loader as lazy

# Lazy load ML dependencies
tf = lazy.load("tensorflow", require="AFL-automation[ml]")
gpflow = lazy.load("gpflow", require="AFL-automation[ml]")
set_trainable = lazy.load("gpflow.set_trainable", require="AFL-automation[ml]")
HGP = lazy.load("AFL.agent.HscedGaussianProcess", require="AFL-automation[ml]")
NaturalGradient = lazy.load("gpflow.optimizers.NaturalGradient", require="AFL-automation[ml]")

from numpy.polynomial import chebyshev, legendre, polynomial


class Scattering_generator():
    """
    A class to interpolate the SAS data across processing and composition dimensions.
    
    There are a few ways to do this, reducing the dimensionality with a polynomial fit has proved to be one good way to interpolate the GP. 
    Other strategies are to fit a model of intensity as a function of Q values. One can incorporate the uncertainties in intensities in a
    Heteroscedastic way. (smearing of the dQ is harder to envision, but likely possible)
    

    slay queen! generate that SAS (or spectroscopy)
    """
    def __init__(self, dataset=None, polytype=None, polydeg=20):
        self.dataset = dataset
        self.polynomial_type = polytype
        self.polynomialfit = None
        self.Y_unct = None
        
        self.X_raw = xr.DataArray(np.array([self.dataset[i].values for i in self.dataset.attrs['components'][1:]]).T) #produces an N x M array N is the number of samples, M is the number of dimensions
        # self.Y_raw = self.dataset.SAS[:,(self.dataset.q > 1e-2) & (self.dataset.q < 2.5e-1)].values # produces an N x K array N is the number of training data points, K is the number of scattering values 
        self.Y_raw = self.dataset.SAS.sel(q=slice(self.dataset.attrs['SAS_savgol_xlo'],self.dataset.attrs['SAS_savgol_xhi']))
        try:
            self.Y_unct = self.dataset.SAS_uncertainty.sel(q=slice(self.dataset.attrs['SAS_savgol_xlo'],self.dataset.attrs['SAS_savgol_xhi']))
        except:
            pass
        self.q = self.dataset.q.sel(q=slice(self.dataset.attrs['SAS_savgol_xlo'],self.dataset.attrs['SAS_savgol_xhi']))
        # print(self.Y_raw.shape, self.q.shape)
        # print(np.min(self.Y_raw,axis=1),np.max(self.Y_raw,axis=1))
        
       
        #correction terms so that the GP works well and can convert back to real units
        self.X_mu  = None     
        self.X_std  = None    
        self.Y_mu  = None
        self.Y_std  = None
        
        self.predictive_mean = None
        self.predictive_variance = None
        
        #construct a kernel for fitting a GP model
        self.optimizer = tf.optimizers.Adam(learning_rate=0.001)
        self.kernel = gpflow.kernels.Matern52(variance=1.0, lengthscales=(1e-1))
        self.opt_HPs = []

        
        #fit the raw data to a polynomial for dimensionality reduction
        if self.polynomial_type == None:
            
            self.Y_raw = self.Y_raw.T
            print(self.Y_raw.shape)
            pass
        elif self.polynomial_type == 'chebyshev':
            self.polynomialfit = np.array([chebyshev.chebfit(x=self.q, y=np.log(i), deg=polydeg) for i in self.Y_raw])
            self.Y_raw = self.polynomialfit.T
        elif self.polynomial_type == 'legendre':
            self.polynomialfit = np.array([legendre.legfit(x=self.q, y=np.log(i), deg=polydeg) for i in self.Y_raw])
            self.Y_raw = self.polynomialfit.T
            print(self.Y_raw.shape)
            print('using legendre polynomial fits')
        elif self.polynomial_type == 'polynomial':
            self.polynomialfit = np.array([polynomial.polyfit(x=self.q, y=np.log(i), deg=polydeg) for i in self.Y_raw])
            self.Y_raw = self.polynomialfit.T
        self.standardize_data()
        
        
    def standardize_data(self):
        #####
        #there needs to be some way to set the bounds more intelligently
        #####
        
        
        #the grid of compositions does not always start at 0, this shifts the minimum
        # X_raw = np.array([i - i.min() for i in self.X_raw])
        
        self.Y_mean = [np.mean(i) for i in self.Y_raw] #this should give a mean and stdev for each q value or coefficient
        self.Y_std = [np.std(i) for i in self.Y_raw] #this should give a mean and stdev for each q value or coefficient
        
        
        
        # here we standardized the data between the bounds
        ###
        #Add ranges
        ###
        # print(x)
        # print(self.X_raw.shape)
        # self.X_train = (self.X_raw - self.X_mu)/self.X_std       #sets X_train to be between -1. to 1.
        self.X_train = np.array([(i - i.min())/(i.max() - i.min()) for i in self.X_raw.T]).T                           #sets X_train to be from 0. to 1. along each dimension
        
        
        
        #sets Y_train to be within -1. to 1. for every target parameter
        self.Y_train = np.array([(i - i.mean())/i.std() for i in self.Y_raw], dtype='float64').T         
        # Y = np.array([(i - np.mean(i))/np.std(i) for i in Is], dtype='float64').T

    def construct_model(self, kernel=None, noiseless=False, heteroscedastic=False):
        
        if kernel != None:
            self.kernel = kernel
            
        if (heteroscedastic) & (self.Y_unct!=None):
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
            self.model = gpflow.models.GPR(
                data   = (self.X_train,self.Y_train),
                kernel = self.kernel
            )

            if noiseless:
                # print("assuming noiseless data")
                # self.model.likelihood.variance =  gpflow.likelihoods.Gaussian(variance=noiseless).parameters[0]
                self.model.likelihood.variance = gpflow.likelihoods.Gaussian(variance=1.00001e-6).parameters[0]
                # print(self.model.parameters)
                set_trainable(self.model.likelihood.variance, False)
        
        return self.model
        
        
    def train_model(self,kernel=None, optimizer=None, noiseless=False, heteroscedastic=False, tol=1e-4, niter=21):
        
        if kernel != None:
            self.kernel = kernel
            
        if optimizer != None:
            self.optimizer = optimizer
        
        if (heteroscedastic) & (self.Y_unct!=None):
            likelihood = HGP.HeteroscedasticGaussian()
            data = (self.X_train,np.stack((self.Y_train,self.Y_unct),axis=1))
            #print(data[0].shape,data[1].shape)
            print("model has been made")
            self.model = gpflow.models.VGP(
                data   = data,
                kernel = self.kernel,
                likelihood = likelihood,
                num_latent_gps=1
                
            )
            self.natgrad = NaturalGradient(gamma=0.5) 
            self.adam = tf.optimizers.Adam()
            set_trainable(self.model.q_mu, False)
            set_trainable(self.model.q_sqrt, False)

        else:
            self.model = gpflow.models.GPR(
                data   = (self.X_train,self.Y_train),
                kernel = self.kernel
            )

            if noiseless:
                # print("assuming noiseless data")
                # self.model.likelihood.variance =  gpflow.likelihoods.Gaussian(variance=noiseless).parameters[0]
                self.model.likelihood.variance = gpflow.likelihoods.Gaussian(variance=1.00001e-6).parameters[0]
                # print(self.model.parameters)
                set_trainable(self.model.likelihood.variance, False)
        
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
        
#         if track_hps:
#             fig,ax = plt.subplots(dpi=150)
#             [ax.plot(list(range(niter)),i) for i in np.array(hyperparams).T]
        return self.model

    def generate_SAS(self, coords=[[0,0,0],[1,2,3]]):
        """
        Returns the simulated scattering pattern given the specified coordinates and polynomial type if reduced
        """
        if coords.shape[1] != self.model.data[1].numpy().shape[0]:
            print("error! the coordinates requested to not match the model dimensions")

        #The coordinates being input should be in natural units. They have to be standardized to use the GP model properly
        coords = np.array(coords)
        
        # print(coords.shape,self.X_raw.T.shape)
        # print([(val.max() - val.min()) for idx,val in enumerate(self.X_raw.T)])
        
        coords = np.array([(coords[idx] - val.min().values) / (val.max().values - val.min().values) for idx,val in enumerate(self.X_raw.T)]).T
        
        # for i in range(len(coords)):
        #     print(coords[i],self.X_train[i])
        
        self.predictive_mean, self.predictive_variance = self.model.predict_f(coords)
        self.predictive_mean = self.predictive_mean.numpy()
        self.predictive_variance = self.predictive_variance.numpy()
        
        
        #convert back to model space
        if self.polynomial_type == None:
            spectra = np.array([self.predictive_mean[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_mean))])
            uncertainty_estimates = np.array([self.predictive_variance[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_variance))])
            
        elif self.polynomial_type == 'chebyshev':
            coeffs = np.array([self.predictive_mean[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_mean))])
            uncertainty_estimates = np.array([self.predictive_variance[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_variance))])
            spectra = chebyshev.chebval(x=self.q, c=coeffs)
            
        elif self.polynomial_type == 'legendre':
            coeffs = np.array([self.predictive_mean[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_mean))])
            uncertainty_estimates = np.array([self.predictive_variance[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_variance))])
            spectra = np.array([legendre.legval(x=self.q, c=c,tensor=True) for c in coeffs])
            
        elif self.polynomial_type == 'polynomial':
            coeffs = np.array([self.predictive_mean[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_mean))])
            uncertainty_estimates = np.array([self.predictive_variance[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_variance))])
            spectra = polynomial.polyval(x=self.q, c=coeffs)


        return spectra, uncertainty_estimates

class GenerateScattering():
    """
    This is the wrapper class that enables scattering interpolation within the classifier labels. 
    """
    def __init__(self, dataset=None, polytype=None):
        self.ds_manifest = dataset
        self.sas_generators = [SAS_generator(dataset=dataset.where(dataset.labels == cluster).dropna(dim='sample'), polytype=polytype) for cluster in np.unique(dataset.labels)]
        
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
