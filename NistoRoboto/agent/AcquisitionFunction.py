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
    
    def reset_phasemap(self,pm):
        self.pm = pm.copy()
        
    def reset_mask(self,mask):
        self.mask = mask
    
    def plot(self):
        labels = self.pm.labels.copy()
        if self.mask is not None:
            labels[~self.mask] = np.nan
            mask = self.mask
            
        pm = self.pm.copy(labels=labels)
        ax = pm.plot()
        
        if self.next_sample is not None:
            pm.plot(compositions=self.next_sample,marker='x',color='k',ax=ax)
        return ax
        
    def copy(self):
        return copy.deepcopy(self)

    def execute(self):
        raise NotImplementedError('Subclasses must implement execute!')

    def get_next_sample(self,nth=0,composition_check=None):
        metric = self.pm
        
        if self.mask is None:
            mask = slice(None)
        else:
            mask = self.mask

        while True:
            index = metric.labels.iloc[mask].argsort()[::-1].index[nth]
            composition = metric.compositions.loc[index]
            # print('ALREADY MEASURED')
            # print(composition_check)
            # print('TO MEASURE')
            # print(composition.values)
            # print('DIFF')
            # check = abs(composition_check-composition.values)
            # print(check)
            # check = (abs(composition_check-composition.values)<1)
            if composition_check is None:
                break #all done
            elif (abs(composition_check-composition.values)<1).all(1).any():
                nth+=1
            else:
                break
            
        self.next_sample = composition.to_frame().T
        return self.next_sample

class Variance(Acquisition):
    def __init__(self):
        super().__init__()
        self.name = 'variance'
        
    def calculate_metric(self,GP):
        if self.pm is None:
            raise ValueError('No phase map set for acquisition! Call reset_phasemap!')
            
        self.y_mean,self.y_var = GP.predict(self.pm.compositions)
        self.pm.labels = self.y_var.sum(1)

        return self.pm
    
class Random(Acquisition):
    def __init__(self):
        super().__init__()
        self.name = 'random'
        
    def calculate_metric(self,GP):
        if self.pm is None:
            raise ValueError('No phase map set for acquisition! Call reset_phasemap!')
            
        self.y_mean,self.y_var = GP.predict(self.pm.compositions)
            
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
        
        if ((self.iteration%self.function2_frequency)==0):
            self.logger.info(f'Using acquisition function {self.function2.name} of iteration {self.iteration}')
            self.pm = self.function2.calculate_metric(GP)
        else:
            self.logger.info(f'Using acquisition function {self.function1.name} of iteration {self.iteration}')
            self.pm = self.function1.calculate_metric(GP)
        self.iteration+=1
            
        return self.pm
