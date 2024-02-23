import numpy as np
from PIL import Image


class FileCamera:
    
    def __init__(self):
        pass
        
    def collect(self,fname):
        '''
        
        '''
        
        return np.array(Image.open(fname))
