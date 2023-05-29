import requests, io
import numpy as np
from PIL import Image


def NetworkCamera:
    
    def __init__(self,url):
        self.url = url
        
    def collect(self):
        '''
        
        '''
        
        return np.array(Image.open(io.BytesIO(requests.get(self.url).content)))
