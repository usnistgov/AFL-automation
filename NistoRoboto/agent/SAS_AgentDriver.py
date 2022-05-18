from NistoRoboto.APIServer.client.Client import Client
from NistoRoboto.APIServer.client.OT2Client import OT2Client
from NistoRoboto.shared.utilities import listify
from NistoRoboto.APIServer.driver.Driver import Driver

from math import ceil,sqrt
import json
import time
import requests
import shutil
import datetime
import traceback
import pickle,base64

import pandas as pd
import numpy as np
import pathlib

from NistoRoboto.agent import AcquisitionFunction 
from NistoRoboto.agent import GaussianProcess 
from NistoRoboto.agent import PhaseMap
from NistoRoboto.agent import Similarity 
from NistoRoboto.agent import PhaseLabeler
from NistoRoboto.agent.Serialize import serialize,deserialize
from NistoRoboto.agent.WatchDog import WatchDog

import tensorflow as tf
import gpflow

import uuid

class SAS_AgentDriver(Driver):
    defaults={}
    defaults['compute_device'] = '/device:CPU:0'
    defaults['data_path'] = '/Users/tbm/watchdog_testing/'
    defaults['data_manifest_file'] = 'manifest.csv'
    defaults['save_path'] = '/home/nistoroboto/'
    defaults['data_tag'] = 'default'
    def __init__(self,overrides=None):
        Driver.__init__(self,name='SAS_AgentDriver',defaults=self.gather_defaults(),overrides=overrides)

        self.watchdog = None 
        self.data_manifest = None
        self._app = None
        self.name = 'SAS_AgentDriver'

        self.status_str = 'Fresh Server!'

        self.phasemap_raw = None
        self.phasemap = None
        self.phasemap_labelled = None
        self.dense_pts_per_row = 100
        self.n_cluster = None
        self.similarity = None
        self.stale = True #flag to determine if new point if available
        self.next_sample = None
        self.mask = None
        self.iteration = 0
        
    @property
    def app(self):
        return self._app
    
    @app.setter
    def app(self,value):
        self._app = value
        # if value is not None:
        #     self.reset_watchdog()
        
    def status(self):
        status = []
        status.append(self.status_str)
        status.append(f'Using {self.config["compute_device"]}')
        status.append(f'Data Manifest:{self.config["data_manifest_file"]}')
        status.append(f'Next sample prediction is stale: {self.stale}')
        status.append(f'Iteration {self.iteration}')
        return status
    
    def reset_watchdog(self):
        if not (self.watchdog is None):
            self.watchdog.stop()
            
        if self.app is not None:
            logger = self.app.logger
        else:
            logger = None
        
        path = pathlib.Path(self.config['data_manifest_file'])
        self.watchdog = WatchDog(
            path=path.parent,
            fname=path.name,
            callback=self.update_phasemap,
            cooldown=5,
        )
        self.watchdog.start()
        
    def update_phasemap(self,predict=True):
        self.app.logger.info(f'Updating phasemap with latest data in {self.config["data_manifest_file"]}')
        path = pathlib.Path(self.config['data_path'])
        
        self.data_manifest = pd.read_csv(path/self.config['data_manifest_file'])
        
        compositions = self.data_manifest.drop(['label','fname'],errors='ignore',axis=1)
        labels = pd.Series(np.ones(compositions.shape[0]))
        measurements = []
        for i,row in self.data_manifest.iterrows():
            #measurement = pd.read_csv(path/row['fname'],comment='#').set_index('q').squeeze()
            measurement = pd.read_csv(path/row['fname'],sep=',',comment='#',header=None,names=['q','I']).set_index('q').squeeze()
            measurement.name = row['fname']
            measurements.append(measurement)
        measurements = pd.concat(measurements,axis=1).T #may need to reset_index...
        
        self.set_components(list(compositions.columns.values))
        self.phasemap_raw.append(
                compositions=compositions,
                measurements=measurements,
                labels=labels,
                )
        if predict:
            self.predict()
          

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)
    
    def get_object(self,name):
        return serialize(getattr(self,name))
    
    def set_mask(self,mask,serialized=False):
        if serialized:
            mask = deserialize(mask)
        self.mask = np.array(mask)
        if mask.shape[0]!=self.phasemap_dense.compositions.shape[0]:
            raise ValueError(f'Mask shape {mask.shape} doesn\'t match phasemap: {mask.shape[0]} vs {self.phasemap_dense.compositions.shape[0]}')
    
    def set_components(self,components,pts_per_row=None):
        if pts_per_row is None:
            pts_per_row = self.dense_pts_per_row
        else:
            self.dense_pts_per_row = pts_per_row
        self.app.logger.info(f'Setting components to {components} with dense pts_per_row={pts_per_row}')
        self.phasemap_raw = PhaseMap.PhaseMap(components)
        self.phasemap_dense = PhaseMap.phasemap_grid_factory(components,pts_per_row=pts_per_row)

    def set_similarity(self,name,similarity_params):
        if name=='pairwise':
            self.similarity = Similarity.Pairwise(params=similarity_params)
        else:
            raise ValueError(f'Similarity type not recognized:{name}')

    def set_labeler(self,name):
        if name=='gaussian_mixture_model':
            self.labeler = PhaseLabeler.GaussianMixtureModel()
        else:
            raise ValueError(f'Similarity type not recognized:{name}')
            
    def set_acquisition(self,spec):
        if spec['name']=='variance':
            self.acquisition = AcquisitionFunction.Variance()
        elif spec['name']=='random':
            self.acquisition = AcquisitionFunction.Random()
        elif spec['name']=='combined':
            function1 = spec['function1_name']
            function2 = spec['function2_name']
            function2_frequency= spec['function2_frequency']
            function1 = AcquisitionFunction.Variance()
            function2 = AcquisitionFunction.Random()
            self.acquisition = AcquisitionFunction.IterationCombined(
                function1=function1,
                function2=function2,
                function2_frequency=function2_frequency,
            )
        else:
            raise ValueError(f'Acquisition type not recognized:{name}')
        
    def append_data(self,compositions,measurements,labels):
        compositions = deserialize(compositions)
        measurements = deserialize(measurements)
        labels = deserialize(labels)
        self.phasemap_raw.append(
                compositions=compositions,
                measurements=measurements,
                labels=labels,
                )

    def get_measurements(self,process=True,pedestal=1e-12,serialize=False):
        # should this put the q on logscale? Should we resample data to the sample q-values? geomspaced?
        measurements = self.phasemap_raw.measurements.copy()
        
        #q-range masking
        q = measurements.columns.values
        mask = (q>0.007)&(q<0.11)
        measurements = measurements.loc[:,mask]
        
        #pedestal + log10 normalization
        measurements += pedestal 
        measurements = np.log10(measurements)
        
        #fixing Nan to pedestal values
        measurements[np.isnan(measurements)] = pedestal
        
        #invariant scaling 
        norm = np.trapz(measurements.values,x=measurements.columns.values,axis=1)
        norm = abs(norm)
        measurements = measurements.mul(1/norm,axis=0)

        self.phasemap = self.phasemap_raw.copy()
        self.phasemap.measurements = measurements
        
        return measurements
    
    def predict(self):
        self.app.logger.info('Starting next sample prediction...')
        measurements = self.get_measurements()
        self.similarity.calculate(measurements)

        self.n_cluster,labels,silh = PhaseLabeler.silhouette(self.similarity.W,self.labeler)
        self.app.logger.info(f'Silhouette analysis found {self.n_cluster} clusters')

        self.phasemap_labelled = self.phasemap.copy(labels=labels)
        
        # Predict phase behavior at each point in the phase diagram
        self.app.logger.info(f'Starting gaussian process calculation on {self.config["compute_device"]}')
        with tf.device(self.config['compute_device']):
            self.GP = GaussianProcess.GP(
                self.phasemap_labelled,
                num_classes=self.n_cluster
            )
            kernel = gpflow.kernels.Matern32(variance=0.5,lengthscales=1.0) 
            self.GP.reset_GP(kernel = kernel)          
            self.GP.optimize(1500,progress_bar=True)
        
        self.app.logger.info(f'Calculating acquisition function...')
        check = self.data_manifest[self.phasemap.components].values
        self.acquisition.reset_phasemap(self.phasemap_dense)
        self.acquisition.reset_mask(self.mask)
        self.acquisition.calculate_metric(self.GP)

        self.app.logger.info(f'Finding next sample composition based on acquisition function')
        check = self.data_manifest[self.phasemap.components].values
        self.next_sample = self.acquisition.get_next_sample(composition_check=check)
        self.app.logger.info(f'Next sample is found to be {self.next_sample.squeeze().to_dict()} by acquisition function {self.acquisition.name}')
        self.stale = False
                             
        ## SAVE DATA ##
        uuid_str = str(uuid.uuid4())
        save_path = pathlib.Path(self.config['save_path'])
        params = {}
        params['n_cluster'] = self.n_cluster
        params['gp_y_var'] = self.acquisition.y_var
        params['gp_y_mean'] = self.acquisition.y_mean
        params['labels'] = labels
        params['silh'] = silh
        params['mask'] = self.mask
        params['next_sample'] = self.next_sample
        params['iteration'] = self.iteration
        params['data_tag'] = self.config["data_tag"]
        params['acquisition_object'] = self.acquisition
        params['acquisition_name'] = self.acquisition.name
        params['uuid'] = uuid_str
        with open(save_path/f'parameters_{self.config["data_tag"]}_{uuid_str}.pkl','wb') as f:
            pickle.dump(params,f,-1)
        self.phasemap.save(save_path/f'phasemap_input_{self.config["data_tag"]}_{uuid_str}.pkl')
        self.phasemap_labelled.save(save_path/f'phasemap_labelled_{self.config["data_tag"]}_{uuid_str}.pkl')
        self.acquisition.pm.save(save_path/f'phasemap_acquisition_{self.config["data_tag"]}_{uuid_str}.pkl')
        
        AL_manifest_path = save_path/'manifest.csv'
        if AL_manifest_path.exists():
            self.AL_manifest = pd.read_csv(AL_manifest_path)
        else:
            self.AL_manifest = pd.DataFrame(columns=['uuid','date','time','data_tag','iteration'])
        
        row = {}
        row['uuid'] = uuid_str
        row['date'] =  datetime.datetime.now().strftime('%y%m%d')
        row['time'] =  datetime.datetime.now().strftime('%H:%M:%S')
        row['data_tag'] = self.config['data_tag']
        row['iteration'] = self.iteration
        self.AL_manifest = self.AL_manifest.append(row,ignore_index=True)
        self.AL_manifest.to_csv(AL_manifest_path,index=False)
            
        
        self.iteration+=1
        self.app.logger.info(f'Finished AL iteration {self.iteration}')
    
    @Driver.unqueued()
    def get_next_sample(self):
        self.app.logger.info(f'Calculating acquisition function...')
        check = self.data_manifest[self.phasemap.components].values
        self.acquisition.reset_phasemap(self.phasemap_dense)
        self.acquisition.reset_mask(self.mask)
        self.acquisition.calculate_metric(self.GP)

        self.app.logger.info(f'Finding next sample composition based on acquisition function')
        check = self.data_manifest[self.phasemap.components].values
        self.next_sample = self.acquisition.get_next_sample(composition_check=check)
        self.app.logger.info(f'Next sample is found to be {self.next_sample.squeeze().to_dict()} by acquisition function {self.acquisition.name}')
        obj = serialize((self.next_sample,self.stale))
        self.stale = True
        return obj
        
    


   
