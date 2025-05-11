import requests, io
import numpy as np
import lazy_loader as lazy
cv2 = lazy.load("cv2", require="AFL-automation[vision]")

class USBCamera:
    
    def __init__(self,camid=5):
        self.camid = camid
        self.camera = cv2.VideoCapture(self.camid)
        
    def camera_reset(self):
        self.camera = cv2.VideoCapture(self.camid)
    def collect(self):
        '''
        
        '''
        collected, img = self.camera.read()
        
        return collected, img