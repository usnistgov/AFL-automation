import numpy as np
import copy
import scipy.spatial

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
        return ax
        
    def copy(self):
        return copy.deepcopy(self)

    def execute(self):
        raise NotImplementedError('Subclasses must implement execute!')

    def next_sample(self,GP,nth=0,composition_check=None):
        metric = self.calculate_metric(GP)
        
        if self.mask is None:
            mask = slice(None)
        else:
            mask = self.mask
        while True:
            index = metric.labels.iloc[mask].argsort()[::-1].iloc[nth]
            composition = metric.compositions.loc[index]
            print('ALREADY MEASURED')
            print(composition_check)
            print('TO MEASURE')
            print(composition.values)
            print('DIFF')
            check = abs(composition_check-composition.values)
            print(check)
            check = (abs(composition_check-composition.values)<1)
            if composition_check is None:
                break #all done
            elif (abs(composition_check-composition.values)<1).all(1).any():
                nth+=1
            else:
                break
            
        return composition.to_frame().T

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
