import numpy as np
import copy
import scipy.spatial

from NistoRoboto.agent.PhaseMap import phasemap_grid_factory

class Acquisition:
    def __init__(self,components,pts_per_row=50):
        self.pm = phasemap_grid_factory(components)
        
    def copy(self):
        return copy.deepcopy(self)

    def execute(self):
        raise NotImplementedError('Subclasses must implement execute!')

    def next(self,GP,nth=0,composition_check=None):
        metric = self.calculate_metric(GP)
        
        while True:
            index = metric.labels.argsort()[::-1].iloc[nth]
            composition = metric.compositions.loc[index]
            if composition_check is None:
                break #all done
            elif (composition_check==composition).all(1).any():
                nth+=1
            else:
                break
            
        return composition.to_frame().T

class Variance(Acquisition):
    def calculate_metric(self,GP):
        y_mean,y_var = GP.predict(self.pm.compositions)
        self.pm.labels = y_var.sum(1)

        return self.pm
