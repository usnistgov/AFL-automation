import pandas as pd
import numpy as np
import copy
import scipy.spatial
import random
import logging

from NistoRoboto.agent.PhaseMap import phasemap_grid_factory
#move dense_pm definition outside of this class
#move to driver,make settable here and in driver
#pass make to driver

class Acquisition:
    def __init__(self):
        self.pm = None
        self.mask = None
        self.y_mean = None
        self.y_var = None
        self.next_sample = None
        self.logger = logging.getLogger()
        self.composition_tol = 0.1
    
    def reset_phasemap(self,pm):
        self.pm = pm.copy()
        
    def reset_mask(self,mask):
        self.mask = mask
    
    def plot(self,**kwargs):
        labels = self.pm.labels.copy()
        if self.mask is not None:
            labels[~self.mask] = np.nan
            mask = self.mask
            
        pm = self.pm.copy(labels=labels)
        ax = pm.plot(**kwargs)
        
        if self.next_sample is not None:
            pm.plot(compositions=self.next_sample,marker='x',color='white',ax=ax)
        return ax
        
    def copy(self):
        return copy.deepcopy(self)

    def execute(self):
        raise NotImplementedError('Subclasses must implement execute!')

    def get_next_sample(self,nth=0,composition_check=None):
        metric = self.pm
        
        if np.all(np.isnan(metric.labels.unique())):
            sample_randomly = True
        else:
            sample_randomly = False


                  
        if self.mask is None:
            mask = slice(None)
        else:
            mask = self.mask

        while True:
            if nth>=metric.labels.iloc[mask].shape[0]:
                raise ValueError(f'No next sample found! Searched {nth} iterations from {metric.labels.iloc[mask].shape[0]} labels!')
            
            if sample_randomly:
                self.index=metric.labels.iloc[mask].sample(frac=1).index[0]
                composition = metric.compositions.loc[self.index]
            else:
                self.argsort = metric.labels.iloc[mask].argsort()[::-1]
                self.index = metric.labels.iloc[mask].iloc[self.argsort].index[0]
                composition = metric.compositions.loc[self.index]
                
            if composition_check is None:
                break #all done
            elif (abs(composition_check-composition.values)<self.composition_tol).all(1).any():
                nth+=1
            else:
                break

            if nth>1000:
                raise ValueError('Next sample finding failed to converge!')
            
        self.next_sample = composition.to_frame().T
        return self.next_sample

class Variance(Acquisition):
    def __init__(self):
        super().__init__()
        self.name = 'variance'
        
    def calculate_metric(self,GP):
        if self.pm is None:
            raise ValueError('No phase map set for acquisition! Call reset_phasemap!')
            
        self.y_mean,self.y_var = GP.predict(self.pm.compositions.astype(float))
        self.pm.labels = self.y_var.sum(1)

        return self.pm
    
class Random(Acquisition):
    def __init__(self):
        super().__init__()
        self.name = 'random'
        
    def calculate_metric(self,GP):
        if self.pm is None:
            raise ValueError('No phase map set for acquisition! Call reset_phasemap!')
            
        self.y_mean,self.y_var = GP.predict(self.pm.compositions.astype(float))
            
        indices = np.arange(self.pm.compositions.shape[0])
        random.shuffle(indices)
        self.pm.labels = pd.Series(indices)
        return self.pm
    
class IterationCombined(Acquisition):
    def __init__(self,function1,function2,function2_frequency=5):
        super().__init__()
        self.function1 = function1
        self.function2 = function2
        self.name = 'IterationCombined'  
        self.name += '-'+function1.name
        self.name += '-'+function2.name
        self.iteration = 1
        self.function2_frequency=function2_frequency
        
    def reset_phasemap(self,pm):
        self.function1.reset_phasemap(pm)
        self.function2.reset_phasemap(pm)
        self.pm = pm
        
    def reset_mask(self,mask):
        self.function1.reset_mask(mask)
        self.function2.reset_mask(mask)
        self.mask = mask
        
    def calculate_metric(self,GP):
        if self.function1.pm is None:
            raise ValueError('No phase map set for acquisition! Call reset_phasemap!')

        self.y_mean,self.y_var = GP.predict(self.pm.compositions)
        
        if ((self.iteration%self.function2_frequency)==0):
            print(f'Using acquisition function {self.function2.name} of iteration {self.iteration}')
            self.pm = self.function2.calculate_metric(GP)
        else:
            print(f'Using acquisition function {self.function1.name} of iteration {self.iteration}')
            self.pm = self.function1.calculate_metric(GP)
        self.iteration+=1
            
        return self.pm
