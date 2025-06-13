import pathlib,glob,os,datetime
import matplotlib.pyplot as plt
import numpy as np
import cv2
from PIL import Image
from skimage import data, color
from skimage.transform import hough_circle, hough_circle_peaks,hough_ellipse
from skimage.feature import canny
from skimage.draw import circle_perimeter
from skimage.util import img_as_ubyte
from skimage.color import rgb2gray
from AFL.automation.APIServer.Driver import Driver
import time


class OpticalTurbidity(Driver): 
    defaults = {}
    defaults['hough_radii'] = 98
    defaults['row_crop'] = [0,479]
    defaults['col_crop'] = [0,479]
    defaults['camera_id'] = 5 #0 is the opentrons camera
    defaults['save_path'] = '/home/afl642/2305_SINQ_TurbidityImages/'
    
    def __init__(self,camera,overrides=None):
        '''
        Initalize OPticalTurbidity calculator driver
        '''
        self.camera = camera
        self.empty_img = None
        Driver.__init__(self,name='OpticalTurbidity',defaults=self.gather_defaults(),overrides=overrides)
        
        
    def measure(self,set_empty=False, plotting=False,**kwargs):
        """
        This is an optical turbidity measurement observing the sans cell
        ------------------------
        
        empty_fn: (str) is the path to the empty SANS cell image
        
        filled_fn: (str) is the path to the filled SANS cell image
        """
        row_crop = self.config['row_crop']
        col_crop = self.config['col_crop']
        hough_radii = self.config['hough_radii']
        print('crops: ',row_crop,col_crop)
        print('hough_radii', hough_radii)
        name = ''
        if 'name' in kwargs.keys():
                name = kwargs['name']
                del kwargs['name'] 
        print("attempting to collect camera image")
        #loaded SANS cell image
        self.camera.camera_reset()
        time.sleep(0.2)
        collected, img = self.camera.collect(**kwargs)
        print(collected, img)
        if collected:
            print('collected image')
            measurement_img = img_as_ubyte(rgb2gray(img))
        else:
            self.camera.camera_reset()
            print("trying to reset camera connection")
            collected, img = self.camera.collect(**kwargs)
            if collected:
                measurement_img = img_as_ubyte(rgb2gray(img))
                print('success on retry')
            else:
                print('failed to recollect')
        #measurement_img = img_as_ubyte(rgb2gray(np.array(Image.open(filled_fn))))#[:,:650]
        if set_empty:
            self.empty_img = measurement_img
            print('setting empty image', measurement_img)
            return 0,[0,0]
        else:
            print('measuring turbidity')
            measurement_img = measurement_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]
        print('measurement image: ', measurement_img.shape, type(measurement_img))
        #empty SANS cell image for masking
        if self.empty_img is not None:
            empty_img = self.empty_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]#[:,:650]
        else:
            raise ValueError('need to set empty before measuring')
        
        #Place to fix edge detection
        edges = canny(empty_img, sigma=2, low_threshold=10, high_threshold=50)
    
    
        # Detect radii
        hough_radii = [hough_radii]
        hough_res = hough_circle(edges, hough_radii)
    
        # Select the most prominent circle
        accums, cx, cy, radii = hough_circle_peaks(hough_res, hough_radii,
                                                   total_num_peaks=1)
        #mask grid
        y = np.arange(empty_img.shape[0])
        x = np.arange(empty_img.shape[1])
        X,Y = np.meshgrid(x,y)
    
        XX = X-cx
        YY = Y-cy
    
        R = np.sqrt(XX*XX+YY*YY)
    
        mask = R<radii
#         print(mask.shape, np.min(mask),np.max(mask))
#         print(empty_img.shape, np.min(empty_img),np.max(empty_img))
        
        # plt.imshow(image)
        # plt.imshow(np.where(mask,0.0,np.nan))
        
        # # Draw them
        # fig, ax = plt.subplots(ncols=1, nrows=1, figsize=(10, 4))
        # image = color.gray2rgb(image)
        # for center_y, center_x, radius in zip(cy, cx, radii):
        #     circy, circx = circle_perimeter(center_y, center_x, radius,
        #                                     shape=image.shape)
        #     image[circy, circx] = (220, 20, 20)
     
        empty_intensity = empty_img[mask]
        filled_intensity = measurement_img[mask]
        
#         print(empty_intensity.shape)
#         print(filled_intensity.shape)
#         print(type(empty_intensity))
#         print(type(filled_intensity))
        
#         print(np.sum(empty_intensity<0))
#         print(np.sum(filled_intensity<0))
        
#         print(np.min(empty_intensity))
#         print(np.max(empty_intensity))
        pedestal = np.abs(np.min(empty_intensity))+1
#         print(pedestal)
#         print(np.min(empty_intensity)+pedestal)
        #normalize the filled cell intensity by the empty cell intensity
        norm_intensity = (np.array(filled_intensity, dtype=float)+pedestal)/(np.array(empty_intensity,dtype=float)+pedestal)
        norm_intensity = np.nan_to_num(norm_intensity,nan=1)
        turbidity_metric = np.average(norm_intensity)

        if type(turbidity_metric) == np.ndarray:
            turbidity_metric = turbidity_metric.tolist()
        if type(cx) == np.ndarray:
            cx = cx.tolist()
        if type(cy) == np.ndarray:
            cy = cy.tolist()
        #plotting
        if plotting:
#             cv2.imwrite( str(pathlib.Path(self.config['save_path'])/f'{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}-turbidity0.png'),empty_img)
            
#             cv2.imwrite(str(pathlib.Path(self.config['save_path'])/f'{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}-turbidity1.png'),measurement_img)
            fig,ax = plt.subplots(1,2)
            ax[0].imshow(empty_img)
            ax[0].imshow(np.where(mask,0.0,np.nan))
            ax[1].imshow(measurement_img)
            ax[1].imshow(np.where(mask,0.0,np.nan))
            fig.suptitle(f'Turbidity metric {np.round(turbidity_metric,2)}')
            plt.savefig(pathlib.Path(self.config['save_path'])/f'{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}-turbidity0.png')
            plt.close(fig)
    
            fig,ax = plt.subplots(1,2)
            ax[0].imshow(empty_img)
            ax[0].imshow(np.where(~mask,0.0,np.nan))
            ax[1].imshow(measurement_img)
            ax[1].imshow(np.where(~mask,0.0,np.nan))
            fig.suptitle(f'Turbidity metric {np.round(turbidity_metric,2)}')
            plt.savefig(pathlib.Path(self.config['save_path'])/f'{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}-turbidity1.png')
#             plt.show()
            plt.close(fig)
        if self.data is not None:
                self.data['located_center'] = [cx,cy]  
                self.data['name'] = name 
                self.data.add_array('turbidity',[turbidity_metric]) 
        #returns the turbidity value in normalized units, the center of the circular mask and the radius as a list
        return  turbidity_metric, [cx, cy]



_DEFAULT_CUSTOM_CONFIG = {
        '_classname': 'AFL.automation.instrument.optical_turbidity.OpticalTurbidity',
        '_args': [
            {'_classname': 'AFL.automation.instrument.network_camera.NetworkCamera',
             '_args' : [
                 'http://afl-video:8081/103/current'
             ]
             }
        ]
}
_DEFAULT_CUSTOM_PORT = 5001
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
