import numpy as np
import xarray as xr
import tensorflow as tf
import gpflow
from numpy.polynomial import chebyshev, legendre, polynomial
from gpflow import set_trainable
from AFL.agent import HscedGaussianProcess as HGP
from gpflow.optimizers import NaturalGradient
import itertools

# #tentative
# import geopandas as gpd
# from longsgis import voronoiDiagram4plg

from shapely import geometry, STRtree, unary_union, Point, distance, MultiPoint
from shapely.ops import nearest_points
import alphashape

class Interpolator():
    def __init__(self, dataset):
        self.defaults = {}
        self.defaults['X_data_pointer'] = 'components'
        self.defaults['X_data_exclude']  = 'P188' #typically the solutes components
        self.defaults['Y_data_filter']  = ('SAS_savgol_xlo', 'SAS_savgol_xhi')
        self.defaults['Y_data_pointer'] = 'SAS'
        self.defaults['Y_data_coord']  = 'q'
        
        self.dataset = dataset
        
        
        #construct a kernel for fitting a GP model
        self.optimizer = tf.optimizers.Adam(learning_rate=0.001)
        self.kernel = gpflow.kernels.Matern52(variance=1.0, lengthscales=(1e-1))
        self.opt_HPs = []
        
    def get_defaults(self):
        return self.defaults
    
    def set_defaults(self,default_dict):
        self.defaults = default_dict
        
    def load_data(self, dataset=None):
        if isinstance(self.dataset,xr.core.dataset.Dataset)==False:
            self.dataset = dataset
        self.defaults['X_data_range']   = [f'{component}_range' for component in self.dataset.attrs[self.defaults['X_data_pointer']] if component not in self.defaults['X_data_exclude']]
        
        try: 
            #produces an N x M array N is the number of samples, M is the number of dimensions N is the number of input points
            self.X_raw = xr.DataArray(np.array([self.dataset[i].values for i in self.dataset.attrs[self.defaults['X_data_pointer']] if i not in self.defaults['X_data_exclude']]).T) 
            self.X_ranges = [self.dataset.attrs[i] for i in self.defaults['X_data_range']]
           # print(self.X_ranges)

            #produces an N x K array N is the number of training data points, K is the number of scattering values
            if None not in self.defaults['Y_data_filter']:
                self.Y_raw = self.dataset[self.defaults['Y_data_pointer']].sel({self.defaults['Y_data_coord']:slice(self.dataset.attrs[self.defaults['Y_data_filter'][0]],self.dataset.attrs[self.defaults['Y_data_filter'][1]])}).T
            else:
                self.Y_raw = self.dataset[self.defaults['Y_data_pointer']].T
            #print(self.Y_raw.shape)
        except:
            raise ValueError("One or more of the inputs X or Y are not correct. Check the defaluts")
       # print(self.X_raw.shape, self.Y_raw.shape)
        
        
    def standardize_data(self):
        #####
        #if there is only one data point, there is an issue in how the X_train data standardizes. It needs to be set to a default that falls between the range. 
        #####
        
        
        #the grid of compositions does not always start at 0, this shifts the minimum
        if len(self.X_raw) > 1:
            
            
            self.Y_mean = self.Y_raw.mean(dim='sample') #this should give a mean and stdev for each q value or coefficient
            self.Y_std = self.Y_raw.std(dim='sample') #this should give a mean and stdev for each q value or coefficient

            #sets X_train to be from 0. to 1. along each dimension
            #should be determined based on the range of the dataset....
            self.X_train = np.array([(i - self.X_ranges[idx][0])/(self.X_ranges[idx][1] - self.X_ranges[idx][0]) for idx, i in enumerate(self.X_raw.T)]).T                           
            
            #sets Y_train to be within -1. to 1. for every target parameter
            self.Y_train = (self.Y_raw - self.Y_mean)/self.Y_std
            self.Y_train = self.Y_train.values.T
            
        else:
            self.Y_mean = self.Y_raw.mean(dim='sample')
            self.Y_std = self.Y_raw.std(dim='sample')
            
            self.X_train = np.array([(i - self.X_ranges[idx][0])/(self.X_ranges[idx][1] -  self.X_ranges[idx][0]) for idx, i in enumerate(self.X_raw.T)]).T
            ## the best I can do is subtract the mean of the data. If the training data are scalars, not spectra, then there will be no stdev for one point
            self.Y_train = self.Y_raw.values.T
            
    def construct_model(self, kernel=None, noiseless=False, heteroscedastic=False):
        
        if kernel != None:
            self.kernel = kernel
            
        ### Due to the difficulty of doing the heteroscedastic modeling, I would avoid this for now
        if (heteroscedastic):# & (self.Y_unct!=None):
            likelihood = HGP.HeteroscedasticGaussian()
            data = (self.X_train,np.stack((self.Y_train,self.Y_unct),axis=1))
            # print(data[0].shape,data[1].shape)
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
        #print(self.X_train.shape,self.Y_train.shape)
        if kernel != None:
            self.kernel = kernel
            
        if optimizer != None:
            self.optimizer = optimizer
        
        ## load the model if it is not there already (because it wasn't instantiated on __init__ not sure how to use isinstance() here
        
        if 'X_train' not in list(self.__dict__):#isinstance(self.X_train, type(np.ndarray)) == False:
            self.standardize_data()
            self.construct_model(kernel=kernel, noiseless=noiseless, heteroscedastic=heteroscedastic)
            
        if 'model' not in list(self.__dict__):
            self.construct_model(kernel=kernel, noiseless=noiseless, heteroscedastic=heteroscedastic)
            
            
        #print(self.model.data)
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
       # print(np.any(X_new <0.),np.any(X_new >1.))
        
        #check to see if the input coordinates and dimensions are correct:
        if np.any(X_new< 0.) or np.any(X_new> 1.):
            raise ValueError('check requested values for X_new, data not within model range')
        
        self.predictive_mean, self.predictive_variance = self.model.predict_f(X_new)
        self.predictive_mean = self.predictive_mean.numpy()
        self.predictive_variance = self.predictive_variance.numpy()
        
        
        #un-standardize
        mean = np.array([self.predictive_mean[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_mean))])
        variance = np.array([self.predictive_variance[i] * self.Y_std + self.Y_mean for i in range(len(self.predictive_variance))])
        

        return mean, variance
    

class ClusteredGPs():
    """
    This is the wrapper class that enables scattering interpolation within the classifier labels. It presupposes that the dataset or manifest contains a datavariable called labels and that it is 
    """
    def __init__(self, dataset):
        self.ds_manifest = dataset
        self.datasets = [dataset.where(dataset.labels == cluster).dropna(dim='sample') for cluster in np.unique(dataset.labels)]
        self.independentGPs = [Interpolator(dataset=dataset.where(dataset.labels == cluster).dropna(dim='sample')) for cluster in np.unique(dataset.labels)]
        
        #####
        #Note: Edge cases can make this difficult. overlapping clusters are bad (should be merged), and clusters of size N < (D + 1) input dimensions will fault 
        #    on concave hull concstruction. so the regular point, or line constructions will be used instead. (for two input dimensions)
        #####
    def get_defaults(self):
        """
        returns a list of dictionaries corresponding to the default data pointers for each GP model 
        """
        return [gpmodel.defaults for gpmodel in self.independentGPs]
    
    def set_defaults(self,default_dict):
        """
        check the default params, but these are pointers to the values in the dataset
        """
        for idx in range(len(self.independentGPs)):
            self.independentGPs[idx].defaults = default_dict
        
    def load_datasets(self,gplist=None):
        """
        This function instantiates the X_raw, Y_raw data with the appropriate filtering given the defaults dictionaries
        """
        if isinstance(gplist,type(None)):
            gplist = self.independentGPs
        for gpmodel in gplist:
            gpmodel.load_data()
            gpmodel.standardize_data()
            
    def define_domains(self, gplist=None, alpha=0.1):
        """
        define domains will generate the shapely geometry objects for the given datasets X_raw data points.
        """
        
        ## this isn't written well for arbitrary dimensions...
        self.domain_geometries = []
        
        if isinstance(gplist,type(None)):
            gplist = self.independentGPs
        
        for idx, gpmodel in enumerate(gplist):
            # print(len(gpmodel.X_raw))
            if len(gpmodel.X_raw.values) == 1:
                domain_polygon = geometry.point.Point(gpmodel.X_raw.values)
            elif len(gpmodel.X_raw.values) == 2:
                domain_polygon = geometry.LineString(gpmodel.X_raw.values)
            else:
                domain_polygon = alphashape.alphashape(gpmodel.X_raw.values,alpha)
            self.domain_geometries.append(domain_polygon)
        return self.domain_geometries
    
    def voronoi_fill(self):
        """
        This likely needs to use geopandas and some voronoi tesellation for polygon inputs. It should fill the space appropriately once the alphashapes are established
        """
        print('current method is kinda busted')
        
        input_data = gpd.GeoDataFrame(data=[f'cell{i}' for i in range(len(union.geoms))],geometry=[geom for geom in union.geoms])
        boundary = shapelyPoly([(-0.5,-0.5),(15.5,-0.5),(15.5,15.5),(-0.5, 15.5)])
        # boundary = shapelyPoly([(0.0, 0.0),(15.0,0.0),(15.0,15.0),(0.0, 15.0)])
        voro = voronoiDiagram4plg(input_data,boundary)
        
        # fig,ax = plt.subplots()
        # for idx, geo in enumerate(voro['geometry']):
        #     points = [csg.concat_GPs[idx].X_raw[:,0],csg.concat_GPs[idx].X_raw[:,1]]
        #     patch=Polygon(geo.exterior.coords,color=f'C{idx+1}',alpha=0.1)
        #     ax.add_patch(patch)
        #     ax.scatter(points[0],points[1],c=f'C{idx}')
        # ax.set(
        #     xlim=(-0.5,15.5),
        #     ylim=(-0.5,15.5)
        # )
            
    def unionize(self,gplist=None, geomlist=None, dslist=None, buffer=0.01):
        """
        determines the union of and indices of potentially conflicting domains. Creates the new indpendent_GPs list that corresponds.
        
        Note! buffer is important here! if a cluster contains a single point or a line, there is a bunch of stuff that breaks. 
        specifying a non-zero buffer will force these lesser dimensional objects to be polygonal and help with all the calculations.
        a large buffer will potentially merge polygons though. exercise caution
        """
        
        #### this bit of header is for generalizability. probably needs to be corrected
        if isinstance(gplist,type(None)):
            gplist = self.independentGPs
        
        if isinstance(geomlist,type(None)):
            geomlist = self.domain_geometries
        
        if isinstance(dslist,type(None)):
            dslist = self.datasets
        
        ### this finds the union between the list of shapely geometries and does the apapropriate tree search for all combinations
        union = unary_union(geomlist).buffer(buffer)
        tree = STRtree(list(union.geoms))
        common_indices = []
        for gpmodel in gplist:
            test_point = gpmodel.X_raw[0]
            common_indices.append(tree.query(Point(test_point), predicate='intersects')[0])
            
        ### this is to concatinate ovelapping datasets into one
        self.union_datasets = []
        for i in np.unique(common_indices):
            #print(i)
            store = [ds for j, ds in zip(common_indices,dslist) if j==i]
            if len(store)>1:
                #print(len(store))
                ds = xr.concat(store,dim='sample')
            else:
                ds = store[0]
            self.union_datasets.append(ds)
        self.union_geometries = union
        
        self.concat_GPs = [Interpolator(dataset=ds) for ds in self.union_datasets]
        return self.concat_GPs, self.union_geometries, common_indices
        
    def train_all(self,kernel=None, optimizer=None, noiseless=True, heteroscedastic=False, niter=21, tol=1e-4, gplist=None):
        if isinstance(gplist,type(None)):
            gplist = self.independentGPs
        self.all_models = [gpmodel.train_model(
            kernel=kernel,
            optimizer=optimizer,
            noiseless=noiseless,
            heteroscedastic=heteroscedastic,
            niter=niter,
            tol=tol) for gpmodel in gplist]
        
    def predict(self, X_new=None,gplist=None,domainlist=None):
        """
        Returns posterior mean and uncertainty of the pattern for the model closest to the input coordinate. Note that the coordinate should be in natural units specified by the Interpolator.predict function
        """
        
        ### first find the model with boundaries closest to the requested input
        distances = []
        
        if isinstance(domainlist,type(None)):
            domains = self.domain_geometries
        
        for idx, geom in enumerate(list(self.union_geometries.geoms)):
            dist = geom.exterior.distance(Point(X_new))
            distances.append(dist)
        # print(distances)
        
        model_idx = np.argmin(distances)
        if isinstance(gplist,type(None)):
            gpmodel = self.independentGPs[model_idx]
        else:
            gpmodel = gplist[model_idx]
        mean, variance = gpmodel.predict(X_new=X_new)
        
        return mean, variance, model_idx