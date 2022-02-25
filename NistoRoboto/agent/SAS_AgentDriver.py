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
    defaults['watch_dir'] = '/Users/tbm/watchdog_testing/'
    defaults['manifest_file'] = 'manifest.csv'
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
        
    @property
    def app(self):
        return self._app
    
    @app.setter
    def app(self,value):
        self._app = value
        if value is not None:
            self.reset_watchdog()
    
    def reset_watchdog(self):
        if not (self.watchdog is None):
            self.watchdog.stop()
            
        if self.app is not None:
            logger = self.app.logger
        else:
            logger = None
        
        self.watchdog = WatchDog(
            path=self.config['watch_dir'],
            fname=self.config['manifest_file'],
            callback=self.update_phasemap,
            cooldown=5,
        )
        self.watchdog.start()
        
    def update_phasemap(self,predict=True):
        self.app.logger.info(f'Updating phasemap with latest data in {self.config["watch_dir"]}')
        path = pathlib.Path(self.config['watch_dir'])
        
        self.manifest = pd.read_csv(path/self.config['manifest_file'])
        
        compositions = self.manifest.drop(['label','fname'],errors='ignore',axis=1)
        labels = pd.Series(np.ones(compositions.shape[0]))
        measurements = []
        for i,row in self.manifest.iterrows():
            measurement = pd.read_csv(path/row['fname'],comment='#').set_index('q').squeeze()
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
        status.append(f'Watching {self.config["manifest_file"]} in {self.config["watch_dir"]}')
        status.append(f'Next sample prediction is stale: {self.stale}')
        return status

    def update_status(self,value):
        self.status_str = value
        self.app.logger.info(value)
    
    def get_object(self,name):
        return serialize(getattr(self,name))

    def set_components(self,components):
        self.phasemap = PhaseMap.PhaseMap(components)

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
        data = self.phasemap.measurements.copy()
        data[data<=0] = 1e-12
        data = np.log10(data)
        self.similarity.calculate(data)

        self.n_cluster,labels,silh = PhaseLabeler.silhouette(self.similarity.W,self.labeler)

        self.phasemap_labelled = self.phasemap.copy(labels=labels)
        
        # Predict phase behavior at each point in the phase diagram
        with tf.device(self.config['compute_device']):
            self.GP = GaussianProcess.GP(
                self.phasemap_labelled,
                num_classes=self.n_cluster
            )
            self.GP.reset_GP()
            self.GP.optimize(1000)
        
        self.acquisition.reset_phasemap(self.phasemap.components)
        self.next_sample = self.acquisition.next_sample(self.GP)
        self.stale = False
        self.app.logger.info('Done predicting next sample!')
    
    @Driver.unqueued()
    def get_next_sample(self):
        obj = serialize((self.next_sample,self.stale))
        self.stale = True
        return obj
        
    


   
