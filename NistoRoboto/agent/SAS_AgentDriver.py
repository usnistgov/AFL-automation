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

class SAS_AgentDriver(Driver):
    defaults={}
    defaults['compute_device'] = '/device:CPU:0'
    defaults['data_path'] = '/Users/tbm/watchdog_testing/'
    defaults['manifest_file'] = 'manifest.csv'
    defaults['save_path'] = '/home/nistoroboto/'
    defaults['data_tag'] = 'default'
    def __init__(self,overrides=None):
        Driver.__init__(self,name='SAS_AgentDriver',defaults=self.gather_defaults(),overrides=overrides)

        self.watchdog = None 
        self.manifest = None
        self._app = None
        self.name = 'SAS_AgentDriver'

        self.status_str = 'Fresh Server!'

        self.phasemap = None
        self.phasemap_labelled = None
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
    
    def reset_watchdog(self):
        if not (self.watchdog is None):
            self.watchdog.stop()
            
        if self.app is not None:
            logger = self.app.logger
        else:
            logger = None
        
        path = pathlib.Path(self.config['manifest_file'])
        self.watchdog = WatchDog(
            path=path.parent,
            fname=path.name,
            callback=self.update_phasemap,
            cooldown=5,
        )
        self.watchdog.start()
        
    def update_phasemap(self,predict=True):
        self.app.logger.info(f'Updating phasemap with latest data in {self.config["manifest_file"]}')
        path = pathlib.Path(self.config['data_path'])
        
        self.manifest = pd.read_csv(path/self.config['manifest_file'])
        
        compositions = self.manifest.drop(['label','fname'],errors='ignore',axis=1)
        labels = pd.Series(np.ones(compositions.shape[0]))
        measurements = []
        for i,row in self.manifest.iterrows():
            #measurement = pd.read_csv(path/row['fname'],comment='#').set_index('q').squeeze()
            measurement = pd.read_csv(path/row['fname'],delim_whitespace=True,comment='#',header=None,names=['q','I']).set_index('q').squeeze()
            measurement.name = row['fname']
            measurements.append(measurement)
        measurements = pd.concat(measurements,axis=1).T #may need to reset_index...
        
        self.set_components(list(compositions.columns.values))
        self.phasemap.append(
                compositions=compositions,
                measurements=measurements,
                labels=labels,
                )
        if predict:
            self.predict()
          
    def status(self):
        status = []
        status.append(self.status_str)
        status.append(f'Using {self.config["compute_device"]}')
        status.append(f'Manifest:{self.config["manifest_file"]}')
        status.append(f'Next sample prediction is stale: {self.stale}')
        status.append(f'Iteration {self.iteration}')
        return status

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
            raise ValueError(f'Mask shape {mask.shape} doesn\'t match phasemap')
    
    def set_components(self,components,pts_per_row=50):
        self.phasemap = PhaseMap.PhaseMap(components)
        self.phasemap_dense = PhaseMap.phasemap_grid_factory(components,pts_per_row=50)
        self.dense_pts_per_row = pts_per_row

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
            
    def set_acquisition(self,name):
        if name=='variance':
            self.acquisition = AcquisitionFunction.Variance()
        else:
            raise ValueError(f'Acquisition type not recognized:{name}')
        
    def append_data(self,compositions,measurements,labels):
        compositions = deserialize(compositions)
        measurements = deserialize(measurements)
        labels = deserialize(labels)
        self.phasemap.append(
                compositions=compositions,
                measurements=measurements,
                labels=labels,
                )

    def predict(self):
        self.app.logger.info('Starting next sample prediction...')
        data = self.phasemap.measurements.copy()
        data[data<=0] = 1e-12
        data = np.log10(data)
        self.similarity.calculate(data)

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
            self.GP.reset_GP()
            self.GP.optimize(3000)
        self.app.logger.info(f'Gaussian process fit to data')
        
        check = self.manifest[self.phasemap.components].values
        print(check)
        self.acquisition.reset_phasemap(self.phasemap_dense)
        self.acquisition.reset_mask(self.mask)
        self.next_sample = self.acquisition.next_sample(self.GP,composition_check=check)
        self.stale = False
        self.app.logger.info(f'Next sample is found to be {self.next_sample.squeeze().to_dict()} by acquisition function {self.acquisition.name}')
                             
        ## SAVE DATA ##
        save_path = pathlib.Path(self.config['save_path'])
        params = {}
        params['n_cluster'] = self.n_cluster
        params['gp_y_var'] = self.acquisition.y_var
        params['gp_y_mean'] = self.acquisition.y_mean
        params['labels'] = labels
        params['silh'] = silh
        params['mask'] = self.mask
        params['next_sample'] = self.next_sample
        with open(save_path/f'parameters_{self.config["data_tag"]}_{self.iteration:04d}.pkl','wb') as f:
            pickle.dump(params,f,-1)
        self.phasemap.save(save_path/f'phasemap_input_{self.config["data_tag"]}_{self.iteration:04d}.pkl')
        self.phasemap_labelled.save(save_path/f'phasemap_labelled_{self.config["data_tag"]}_{self.iteration:04d}.pkl')
        self.acquisition.pm.save(save_path/f'phasemap_acquisition_{self.config["data_tag"]}_{self.iteration:04d}.pkl')
        self.iteration+=1
        self.app.logger.info(f'Finished AL iteration {self.iteration}')
    
    @Driver.unqueued()
    def get_next_sample(self):
        obj = serialize((self.next_sample,self.stale))
        self.stale = True
        return obj
        
    


   
