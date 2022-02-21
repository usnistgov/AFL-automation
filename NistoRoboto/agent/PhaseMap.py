import pickle
import warnings
from copy import deepcopy
from itertools import product

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sklearn.preprocessing import OrdinalEncoder


class PhaseMap:
    '''Container for compositions, measurements, and labels'''
    def __init__(self,components):
        self.model = PhaseMapModel(components)
        self.view = PhaseMapView_MPL()
        
    def __str__(self):
        return f'<PhaseMap {self.shape[0]} pts>'
    
    def __repr__(self):
        return self.__str__()
            
    def __getitem__(self,index):
        composition = self.model.compositions.iloc[index]
        measurement = self.model.measurements.iloc[index]
        label = self.model.labels.iloc[index]
        return (composition,measurement,label)

    @property
    def components(self):
        return self.model.components

    @property
    def ncomponents(self):
        return len(self.model.components)
    
    @property
    def compositions(self):
        return self.model.compositions
    
    @property
    def measurements(self):
        return self.model.measurements
    
    @property
    def labels(self):
        return self.model.labels
    
    @labels.setter
    def labels(self,labels):
        if not isinstance(labels,pd.Series):
            labels = pd.Series(labels.copy())
        self.model.labels = labels.copy()
        
    @property
    def labels_ordinal(self):
        '''Numerical labels sorted by spatial position'''
        self.update_encoder()
        
        labels_ordinal = pd.Series(
            data=self.label_encoder.transform(
                self.labels.values.reshape(-1,1)
            ).flatten(),
            index=self.model.labels.index,
        )
        return labels_ordinal
    
    def update_encoder(self):
        labels_sorted = (
            self.compositions
            .copy()
            .set_index(self.labels)
            .sort_values(self.components[:-1]) # sort by comp1 and then comp2
            .index
            .values
        )
        
        self.label_encoder.fit(labels_sorted.reshape(-1,1))
    
    @property
    def label_encoder(self):
        return self.model.label_encoder
    
    @property
    def shape(self):
        return self.model.compositions.shape
    
    @property
    def size(self):
        return self.model.compositions.size
    
    def copy(self,labels=None):
        if labels is None:
            labels = self.model.labels
           
        if not isinstance(labels,pd.Series):
            labels = pd.Series(labels)
            
        pm = PhaseMap(self.components)
        pm.append(
            compositions = self.model.compositions,
            measurements = self.model.measurements,
            labels = labels,
        )
        return pm
    
    def save(self,fname):
        out_dict = {}
        out_dict['components'] = self.model.components
        out_dict['compositions'] = self.model.compositions
        out_dict['measurements'] = self.model.measurements
        out_dict['labels'] = self.model.labels
        
        if not (fname[-4:]=='.pkl'):
            fname+='.pkl'
        
        with open(fname,'wb') as f:
            pickle.dump(out_dict,f,protocol=-1)
            
    @classmethod
    def load(cls,fname):
        if not (fname[-4:]=='.pkl'):
            fname+='.pkl'
            
        with open(fname,'rb') as f:
            in_dict = pickle.load(f)
        
        pm = cls(in_dict['components'])
        pm.append(
            compositions = in_dict['compositions'],
            measurements = in_dict['measurements'],
            labels       = in_dict['labels'],
        )
        return pm
            
    
    def append(self,compositions,measurements,labels):
        self.model.append(
                compositions=compositions,
                measurements=measurements,
                labels=labels
                )
    
        
    def plot(self,components=None,compositions=None,labels=None,**mpl_kw):
        if (components is None) and (compositions is None) and (labels is None):
            components = self.components.copy()
            labels = self.labels.copy()
            compositions = self.compositions.copy()
            
        if components is not None:
            compositions = self.compositions[components].copy()
            labels = self.labels.copy()
            
        if labels is None:
            components = compositions.columns.values.copy()
            labels = np.ones_like(compositions.shape[0])
            
        ax = None
        if len(components)==2:
            ax=self.view.scatter(compositions,labels=labels,**mpl_kw)
        elif len(components)==3:
            ax=self.view.scatter_ternary(compositions,labels=labels,**mpl_kw)
        else:
            raise ValueError('Unable to plot {len(components)} dimensions.')
        return ax
    
class PhaseMapModel:
    def __init__(self,components):
        self.components = components
        self.compositions = pd.DataFrame(columns=components)
        self.measurements = pd.DataFrame()
        self.labels = pd.Series(dtype=np.float64)
        self.label_encoder = OrdinalEncoder()
        
    def append(self,compositions,labels,measurements):
        self.compositions = pd.concat([self.compositions,compositions],ignore_index=True)
        self.measurements = pd.concat([self.measurements,measurements])
        self.labels = pd.concat([self.labels,labels],ignore_index=True)
        
    
class PhaseMapView_MPL:
    def __init__(self,cmap='jet'):
        self.cmap = cmap
        
    def make_axes(self,components,subplots=(1,1)):
        fig,ax = plt.subplots(*subplots,figsize=(5*subplots[1],4*subplots[0]))
        
        if (subplots[0]>1) or (subplots[1]>1):
            ax = ax.flatten()
            if len(components)==3:
                for cax in ax:
                    format_plot_ternary(ax,*components)
        else:
            if len(components)==3:
                format_plot_ternary(ax,*components)
        return ax
    
    def scatter(self,compositions,labels=None,ax=None,**mpl_kw):
        if ax is None:
            ax = self.make_axes(compositions.columns.values,(1,1))
        
        xy = compositions.values
        
        if 'marker' not in mpl_kw:
            mpl_kw['marker'] = '.'
        if ('cmap' not in mpl_kw) and ('color' not in mpl_kw):
            mpl_kw['cmap'] = self.cmap
            mpl_kw['c'] = labels
        ax.scatter(*xy.T,**mpl_kw)
        return ax
    
    def scatter_ternary(self,compositions,labels=None,ax=None,**mpl_kw):
        if ax is None:
            ax = self.make_axes(compositions.columns.values,(1,1))
        
        xy = ternary2cart(compositions.values)
        
        if 'marker' not in mpl_kw:
            mpl_kw['marker'] = '.'
        if ('cmap' not in mpl_kw) and ('color' not in mpl_kw):
            mpl_kw['cmap'] = self.cmap
            mpl_kw['c'] = labels
        ax.scatter(*xy.T,**mpl_kw)
        return ax
    
    def lines(self,xy,ax=None,label=None):
        if ax is None:
            ax = self.make_axes((1,1))
            
        ax.plot(*xy.T,marker='None',ls=':',label=label)
        return ax

def phasemap_grid_factory(components,pts_per_row=50,basis=100):
    compositions = composition_grid(
            pts_per_row = pts_per_row,
            basis = basis,
            dim=len(components),
            )
    N = compositions.shape[0]
    compositions = pd.DataFrame(compositions,columns=components)
    q = np.geomspace(1e-3,1,25)
    I = np.random.random(25)
    measurements = pd.concat([pd.Series(index=q,data=I) for _ in range(N)],axis=1).T
    labels = pd.Series(np.ones(N))
     
    pm = PhaseMap(components)
    pm.append(
            compositions=compositions,
            measurements=measurements,
            labels=labels,
            )

    return pm


def composition_grid(pts_per_row=50,basis=100,dim=3,eps=1e-9):
    pts = []
    for i in product(*[np.linspace(0,1.0,pts_per_row)]*(dim-1)):
        if sum(i)>(1.0+eps):
            continue
            
        j = 1.0-sum(i)
        
        if j<(0.0-eps):
            continue
        pt = [k*basis for k in [*i,j]]
        pts.append(pt)
    return np.array(pts)

def ternary2cart(compositions):
    '''Ternary composition to Cartesian cooridate'''
    if compositions is None:
        compositions = self.model.compositions
        
    try:
        #Assume pandas
        t = compositions.values.copy()
    except AttributeError:
        # Assume numpy
        t = compositions.copy()
    
    if t.ndim==1:
        t = np.array([t])

    if t.shape[1]!=3:
        raise ValueError('This class only works with ternary (3-component) data!')
        
    # Convert ternary data to cartesian coordinates.
    xy = np.zeros((t.shape[0],2))
    xy[:,1] = t[:,1]*np.sin(60.*np.pi / 180.) / 100.
    xy[:,0] = t[:,0]/100. + xy[:,1]*np.sin(30.*np.pi/180.)/np.sin(60*np.pi/180)
    return xy

def format_plot_ternary(ax,label_a=None,label_b=None,label_c=None):
    ax.axis('off')
    ax.set(
        xlim = [0,1],
        ylim = [0,1],
    )
    ax.plot([0,1,0.5,0],[0,0,np.sqrt(3)/2,0],ls='-',color='k')
    if label_a is not None:
        ax.text(0,0,label_a,ha='right')
    if label_a is not None:
        ax.text(1,0,label_b,ha='left')
    if label_a is not None:
        ax.text(0.5,np.sqrt(3)/2,label_c,ha='center',va='bottom')
