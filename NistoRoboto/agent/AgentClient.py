import requests
import base64
import pickle
from NistoRoboto.APIServer.client.Client import Client
from NistoRoboto.agent.Serialize import deserialize,serialize

class AgentClient(Client):
    '''Communicate with NistoRoboto Agent server 

    '''
    def append_data(self,compositions,measurements,labels):
        json = {}
        json['task_name'] = 'append_data'
        json['compositions'] = serialize(compositions)
        json['measurements'] = serialize(measurements)
        json['labels'] = serialize(labels)
        self.enqueue(**json)
        
    def get_phasemap(self):
        json = {}
        json['task_name']  = 'get_object'
        json['name']  = 'phasemap'
        json['interactive']  = True
        retval = self.enqueue(**json)
        phasemap= deserialize(retval['return_val'])
        return phasemap
    
    def get(self,name):
        json = {}
        json['task_name']  = 'get_object'
        json['name']  = name
        json['interactive']  = True
        retval = self.enqueue(**json)
        obj = deserialize(retval['return_val'])
        return obj
    
    def predict(self):
        kw = {}
        kw['task_name'] = 'predict'
        self.enqueue(**kw)