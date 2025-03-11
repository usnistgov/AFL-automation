import requests, io
import numpy as np
from PIL import Image


class NetworkCamera:
    
    def __init__(self,url):
        self.url = url

    def camera_reset(self):
        pass        
    def collect(self):
        '''
        
        '''
        
        return (True,np.array(Image.open(io.BytesIO(requests.get(self.url).content))))
