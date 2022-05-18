import numpy as np
import copy
import scipy.spatial

import sklearn.mixture 
import sklearn.cluster 
from sklearn.metrics import pairwise

from scipy.spatial.distance import pdist, squareform
from scipy.spatial import distance as dist
from collections import Counter

import warnings 
from sklearn.metrics import silhouette_samples, silhouette_score
from collections import defaultdict


class PhaseLabeler:
    def __init__(self,params=None):
        self.labels = None
        if params is None:
            self.params = {}
        else:
            self.params = params
            
    def copy(self):
        return copy.deepcopy(self)
        
    def __getitem__(self,index):
        return self.labels[index]
    
    def __array__(self,dtype=None):
        return np.array(self.labels).astype(dtype)

    def remap_labels_by_count(self):
        label_map ={}
        for new_label,(old_label,_) in enumerate(sorted(Counter(self.labels).items(),key=lambda x: x[1],reverse=True)):
            label_map[old_label]=new_label
        self.labels = list(map(label_map.get,self.labels))
        
    def label(self):
        raise NotImplementedError('Sub-classes must implement label!')
        
class GaussianMixtureModel(PhaseLabeler):
    def label(self,X,**params):
        if params:
            self.params.update(params)
        self.clf = sklearn.mixture.GaussianMixture(self.params['n_cluster'])
        self.clf.fit(X)
        self.labels = self.clf.predict(X)
        
class SpectralClustering(PhaseLabeler):
    def label(self,X,**params):
        if params:
            self.params.update(params)
            
        self.clf = sklearn.cluster.SpectralClustering(
            self.params['n_cluster'],
            affinity = 'precomputed',  
            assign_labels="discretize",  
            random_state=0,  
            n_init = 1000
        )
        self.clf.fit(X)
        self.labels = self.clf.labels_

def silhouette(X,labeler):
    silh_dict = defaultdict(list)
    max_n = min(X.shape[0],11)
    for n_cluster in range(2,max_n):

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            labeler.label(X,n_cluster=n_cluster)
        labeler.remap_labels_by_count()
        
        if len(np.unique(labeler.labels))==1:
            silh_scores = np.zeros(len(X))
        else:
            silh_scores = silhouette_samples(
                1.0-X,
                labeler,
                metric='precomputed'
            )
        silh_dict['all_scores'].append(silh_scores)
        silh_dict['avg_scores'].append(silh_scores.mean())
        silh_dict['n_cluster'].append(n_cluster)
        silh_dict['labelers'].append(labeler.copy())

    silh_avg = np.array(silh_dict['avg_scores'])
    found = False
    for cutoff in np.arange(0.85,0.4,-0.05):
        idx = np.where(silh_avg>cutoff)[0]
        if idx.shape[0]>0:
            idx = idx[-1]
            found=True
            break
            
    if not found:
        n_cluster = 1
        labels=np.zeros(X.shape[0])
    else:
        n_cluster = silh_dict['n_cluster'][idx]
        labels = silh_dict['labelers'][idx].labels
    return n_cluster,labels,silh_dict
