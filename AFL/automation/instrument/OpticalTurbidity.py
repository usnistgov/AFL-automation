import pathlib,glob,os,datetime
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from skimage import data, color
from skimage.transform import hough_circle, hough_circle_peaks,hough_ellipse
from skimage.feature import canny
from skimage.draw import circle_perimeter
from skimage.util import img_as_ubyte
from skimage.color import rgb2gray
from AFL.automation.APIServer.Driver import Driver


class OpticalTurbidity(Driver): 
    defaults = {}
    defaults['hough_radii'] = 98
    defaults['row_crop'] = [0,1]
    defaults['col_crop'] = [0,1]
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
        
        #loaded SANS cell image
        measurement_img = img_as_ubyte(rgb2gray(self.camera.collect(**kwargs)))
        #measurement_img = img_as_ubyte(rgb2gray(np.array(Image.open(filled_fn))))#[:,:650]
        if set_empty:
            self.empty_img = measurement_img
            return 0,[0,0]
        else:
            measurement_img = measurement_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]
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
        
        #normalize the filled cell intensity by the empty cell intensity
        turbidity_metric = np.average(filled_intensity/empty_intensity)
        
        if type(turbidity_metric) == np.ndarray:
            turbidity_metric = turbidity_metric.tolist()
        if type(cx) == np.ndarray:
            cx = cx.tolist()
        if type(cy) == np.ndarray:
            cy = cy.tolist()
        #plotting
        if plotting:
            # print(idx, measurement_fn, empty_fn)
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
            plt.close(fig)
            
        #returns the turbidity value in normalized units, the center of the circular mask and the radius as a list
        return  turbidity_metric, [cx, cy]
