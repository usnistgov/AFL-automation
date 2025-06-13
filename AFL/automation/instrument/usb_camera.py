import requests, io
import numpy as np
import cv2

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
#         if collected:
#             return np.array(img)

#         else:
#             print("camera client reconnecting")
#             self.camera_reset()
#             print("trying again")
#             collected, img = self.camera.read()
            
#         if collected:
#             print('retry successful!') 
#             return np.array(img)
#         else:
#             print('retry failed :(')
#             return None
            