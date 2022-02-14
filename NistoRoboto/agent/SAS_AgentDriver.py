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

from NistoRoboto.agent import AcquisitionFunction 
from NistoRoboto.agent import GaussianProcess 
from NistoRoboto.agent import PhaseMap 
from NistoRoboto.agent import Similarity 
from NistoRoboto.agent import PhaseLabeler 
from NistoRoboto.agent.Serialize import serialize,deserialize

import tensorflow as tf
import gpflow

class SAS_AgentDriver(Driver):
    defaults={}
    defaults['compute_device'] = '/device:CPU:0'
    def __init__(self,overrides=None):

        Driver.__init__(self,name='SAS_AgentDriver',defaults=self.gather_defaults(),overrides=overrides)

        self.app = None
        self.name = 'SAS_AgentDriver'

        self.status_str = 'Fresh Server!'

        self.phasemap = None
        self.phasemap_labelled = None
        self.n_cluster = None
        self.similarity = None

    def status(self):
        status = []
        status.append(self.status_str)
        status.append(self.config['compute_device'])
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
            self.acquisition = AcquisitionFunction.Variance(self.phasemap.components)
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
        self.similarity.calculate(self.phasemap.measurements.copy())

        self.n_cluster,labels,silh = PhaseLabeler.silhouette(self.similarity.W,self.labeler)

        self.phasemap_labelled = self.phasemap.copy(labels=labels)
        
        # Predict phase behavior at each point in the phase diagram
        with tf.device(self.config['compute_device']):
            GP = GaussianProcess.GP(
                self.phasemap_labelled,
                num_classes=self.n_cluster
            )
            GP.reset_GP()
            GP.optimize(1000)
        
        self.next = self.acquisition.next(GP)
        
    


   
