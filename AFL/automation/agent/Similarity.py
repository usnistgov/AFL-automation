import numpy as np
import copy
import scipy.spatial

from sklearn.mixture import GaussianMixture
from sklearn.cluster import SpectralClustering
from sklearn.metrics import pairwise

from scipy.spatial.distance import pdist, squareform
from scipy.spatial import distance as dist
from collections import Counter


class Similarity:
    def __init__(self,params=None):
        self.W = None
        if params is None:
            self.params = {}
        else:
            self.params = params
    
    def copy(self):
        return copy.deepcopy(self)
    
    def __getitem__(self,index):
        return self.W[index]
    
    def __array__(self,dtype=None):
        return self.W.astype(dtype)
        
    def __mul__(self,other):
        if (self.W is None) or (other.W is None):
            raise ValueError('Must call .embed before combining embeddings')
        new = self.copy()
        new.W = self.W*other.W
        return new
    
    def embed(self):
        raise NotImplementedError('Sub-classes must implement embed!')
        
        
class Pairwise(Similarity):
    def calculate(self,X,**params):
        if params:
            self.params.update(params)
            
        self.W = pairwise.pairwise_kernels(
            X, 
            filter_params=True,  
            **self.params
        )
        return self
    
class Delaunay(Similarity):
    def calculate(self,X):
        """
        Computes the Delaunay triangulation of the given points
        :param x: array of shape (num_nodes, 2)
        :return: the computed adjacency matrix
        """
        tri = scipy.spatial.Delaunay(X)
        edges_explicit = np.concatenate((tri.vertices[:, :2],
                                         tri.vertices[:, 1:],
                                         tri.vertices[:, ::2]), axis=0)
        adj = np.zeros((x.shape[0], x.shape[0]))
        adj[edges_explicit[:, 0], edges_explicit[:, 1]] = 1.
        self.W = np.clip(adj + adj.T, 0, 1) 
        return self
    
    
