import pathlib
import datetime
import pathlib
import datetime
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import lazy_loader as lazy
cv2 = lazy.load("cv2", require="AFL-automation[vision]")
from skimage.transform import hough_circle, hough_circle_peaks
from skimage.transform import hough_circle, hough_circle_peaks
from skimage.feature import canny
from skimage.util import img_as_ubyte
from skimage.color import rgb2gray
from AFL.automation.APIServer.Driver import Driver
import time
import copy
import warnings

try:
    from tiled.queries import Eq
except ImportError:
    Eq = None
    warnings.warn("Cannot import from tiled...empty UUID lookup will not work", stacklevel=2)
import copy
import warnings

try:
    from tiled.queries import Eq
except ImportError:
    Eq = None
    warnings.warn("Cannot import from tiled...empty UUID lookup will not work", stacklevel=2)


class OpticalTurbidity(Driver): 
    defaults = {}
    defaults['hough_radii'] = 98
    defaults['row_crop'] = [0,479]
    defaults['col_crop'] = [0,479]
    defaults['save_path'] = '/home/afl642/2305_SINQ_TurbidityImages/'
    defaults['camera_interface'] = 'http'  # 'http' or 'opencv'
    defaults['camera_url'] = 'http://afl-video:8081/103/current'  # For http interface
    defaults['camera_index'] = 0  # For opencv interface
    defaults['empty_uuid'] = ''  # sample_uuid in tiled
    
    def __init__(self,camera=None,overrides=None):
    defaults['camera_interface'] = 'http'  # 'http' or 'opencv'
    defaults['camera_url'] = 'http://afl-video:8081/103/current'  # For http interface
    defaults['camera_index'] = 0  # For opencv interface
    defaults['empty_uuid'] = ''  # sample_uuid in tiled
    
    def __init__(self,camera=None,overrides=None):
        '''
        Initialize OpticalTurbidity calculator driver
        
        Parameters:
        -----------
        camera : object, optional
            Camera object (e.g., NetworkCamera instance). If None, will be created
            based on camera_interface config setting.
        overrides : dict, optional
            Configuration overrides for PersistentConfig
        Initialize OpticalTurbidity calculator driver
        
        Parameters:
        -----------
        camera : object, optional
            Camera object (e.g., NetworkCamera instance). If None, will be created
            based on camera_interface config setting.
        overrides : dict, optional
            Configuration overrides for PersistentConfig
        '''
        self.camera = camera
        self.empty_img = None
        self._opencv_capture = None  # Cache for OpenCV VideoCapture
        self._opencv_capture = None  # Cache for OpenCV VideoCapture
        Driver.__init__(self,name='OpticalTurbidity',defaults=self.gather_defaults(),overrides=overrides)
        
        # Initialize camera if not provided and interface is http
        if self.camera is None and self.config['camera_interface'] == 'http':
            from AFL.automation.instrument.NetworkCamera import NetworkCamera
            self.camera = NetworkCamera(self.config['camera_url'])
    
    def _collect_image(self, **kwargs):
        """
        Collect an image based on the configured camera_interface.
        
        Returns:
        --------
        tuple : (collected: bool, img: np.ndarray)
            collected indicates success, img is the image array
        """
        interface = self.config['camera_interface']
        
        if interface == 'http':
            # Use NetworkCamera (backwards compatible)
            if self.camera is None:
                from AFL.automation.instrument.NetworkCamera import NetworkCamera
                if 'camera_url' not in self.config:
                    raise ValueError("camera_url must be set in config when camera_interface='http'")
                self.camera = NetworkCamera(self.config['camera_url'])
            return self.camera.collect(**kwargs)
        
        elif interface == 'opencv':
            # Use OpenCV VideoCapture directly
            try:
                cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
            except Exception as e:
                raise ImportError(
                    "opencv-python is required for camera_interface='opencv'. "
                    f"Install with: pip install AFL-automation[vision]. Error: {e}"
                )
            
            if 'camera_index' not in self.config:
                raise ValueError("camera_index must be set in config when camera_interface='opencv'")
            
            camera_index = self.config['camera_index']
            
            # Initialize or reuse VideoCapture
            if self._opencv_capture is None:
                self._opencv_capture = cv2_module.VideoCapture(camera_index)
            
            collected, img = self._opencv_capture.read()
            return collected, img
        
        else:
            raise ValueError(
                f"Unsupported camera_interface: '{interface}'. "
                "Supported values are: 'http', 'opencv'"
            )
    
    def _reset_camera(self):
        """
        Reset the camera connection based on the configured camera_interface.
        """
        interface = self.config['camera_interface']
        
        if interface == 'http':
            # NetworkCamera reset is a no-op, but call it for consistency
            if self.camera is not None:
                self.camera.camera_reset()
        
        elif interface == 'opencv':
            # Reinitialize VideoCapture
            if self._opencv_capture is not None:
                self._opencv_capture.release()
            try:
                cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
            except Exception as e:
                raise ImportError(
                    "opencv-python is required for camera_interface='opencv'. "
                    f"Install with: pip install AFL-automation[vision]. Error: {e}"
                )
            camera_index = self.config.get('camera_index', 0)
            self._opencv_capture = cv2_module.VideoCapture(camera_index)
        
        # No else needed - _collect_image will catch invalid interface

    def _build_dataset(
        self,
        *,
        name,
        turbidity_metric,
        measurement_img,
        empty_img,
        mask,
        cx,
        cy,
        empty_from_measurement=False,
        is_empty_reference=False,
    ):
        ds = xr.Dataset()
        ds.attrs['located_center'] = [cx, cy]
        ds.attrs['name'] = name
        ds.attrs['turbidity_metric'] = turbidity_metric
        ds.attrs['empty_uuid'] = self.config.get('empty_uuid', '')
        ds.attrs['empty_available'] = not empty_from_measurement
        ds.attrs['is_empty_reference'] = is_empty_reference
        ds['turbidity'] = turbidity_metric
        ds['img'] = (('px','py'), measurement_img)
        ds['img_MT'] = (('px','py'), empty_img)
        ds['mask'] = (('px','py'), mask)
        return ds
        # Initialize camera if not provided and interface is http
        if self.camera is None and self.config['camera_interface'] == 'http':
            from AFL.automation.instrument.NetworkCamera import NetworkCamera
            self.camera = NetworkCamera(self.config['camera_url'])
    
    def _collect_image(self, **kwargs):
        """
        Collect an image based on the configured camera_interface.
        
        Returns:
        --------
        tuple : (collected: bool, img: np.ndarray)
            collected indicates success, img is the image array
        """
        interface = self.config['camera_interface']
        
        if interface == 'http':
            # Use NetworkCamera (backwards compatible)
            if self.camera is None:
                from AFL.automation.instrument.NetworkCamera import NetworkCamera
                if 'camera_url' not in self.config:
                    raise ValueError("camera_url must be set in config when camera_interface='http'")
                self.camera = NetworkCamera(self.config['camera_url'])
            return self.camera.collect(**kwargs)
        
        elif interface == 'opencv':
            # Use OpenCV VideoCapture directly
            try:
                cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
            except Exception as e:
                raise ImportError(
                    "opencv-python is required for camera_interface='opencv'. "
                    f"Install with: pip install AFL-automation[vision]. Error: {e}"
                )
            
            if 'camera_index' not in self.config:
                raise ValueError("camera_index must be set in config when camera_interface='opencv'")
            
            camera_index = self.config['camera_index']
            
            # Initialize or reuse VideoCapture
            if self._opencv_capture is None:
                self._opencv_capture = cv2_module.VideoCapture(camera_index)
            
            collected, img = self._opencv_capture.read()
            return collected, img
        
        else:
            raise ValueError(
                f"Unsupported camera_interface: '{interface}'. "
                "Supported values are: 'http', 'opencv'"
            )
    
    def _reset_camera(self):
        """
        Reset the camera connection based on the configured camera_interface.
        """
        interface = self.config['camera_interface']
        
        if interface == 'http':
            # NetworkCamera reset is a no-op, but call it for consistency
            if self.camera is not None:
                self.camera.camera_reset()
        
        elif interface == 'opencv':
            # Reinitialize VideoCapture
            if self._opencv_capture is not None:
                self._opencv_capture.release()
            try:
                cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
            except Exception as e:
                raise ImportError(
                    "opencv-python is required for camera_interface='opencv'. "
                    f"Install with: pip install AFL-automation[vision]. Error: {e}"
                )
            camera_index = self.config.get('camera_index', 0)
            self._opencv_capture = cv2_module.VideoCapture(camera_index)
        
        # No else needed - _collect_image will catch invalid interface

    def _build_dataset(
        self,
        *,
        name,
        turbidity_metric,
        measurement_img,
        empty_img,
        mask,
        cx,
        cy,
        empty_from_measurement=False,
        is_empty_reference=False,
    ):
        ds = xr.Dataset()
        ds.attrs['located_center'] = [cx, cy]
        ds.attrs['name'] = name
        ds.attrs['turbidity_metric'] = turbidity_metric
        ds.attrs['empty_uuid'] = self.config.get('empty_uuid', '')
        ds.attrs['empty_available'] = not empty_from_measurement
        ds.attrs['is_empty_reference'] = is_empty_reference
        ds['turbidity'] = turbidity_metric
        ds['img'] = (('px','py'), measurement_img)
        ds['img_MT'] = (('px','py'), empty_img)
        ds['mask'] = (('px','py'), mask)
        return ds
        
    def measure(self,set_empty=False, plotting=False,**kwargs):
        """
        This is an optical turbidity measurement observing the sans cell
        ------------------------
        
        Parameters:
        -----------
        set_empty : bool, optional
            If True, sets the current image as the empty reference image
        plotting : bool, optional
            If True, saves diagnostic plots
        **kwargs : dict
            Additional arguments passed to image collection
        
        Configuration:
        --------------
        The image source is controlled by PersistentConfig settings:
        - camera_interface: 'http' or 'opencv' (default: 'http')
        - camera_url: URL for HTTP interface (required when camera_interface='http')
        - camera_index: Device index for OpenCV interface (required when camera_interface='opencv')
        
        Returns:
        --------
        xarray.Dataset
            Dataset with turbidity measurements and images. When set_empty=True,
            the dataset contains the captured empty reference image.
        Parameters:
        -----------
        set_empty : bool, optional
            If True, sets the current image as the empty reference image
        plotting : bool, optional
            If True, saves diagnostic plots
        **kwargs : dict
            Additional arguments passed to image collection
        
        Configuration:
        --------------
        The image source is controlled by PersistentConfig settings:
        - camera_interface: 'http' or 'opencv' (default: 'http')
        - camera_url: URL for HTTP interface (required when camera_interface='http')
        - camera_index: Device index for OpenCV interface (required when camera_interface='opencv')
        
        Returns:
        --------
        xarray.Dataset
            Dataset with turbidity measurements and images. When set_empty=True,
            the dataset contains the captured empty reference image.
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
        self._reset_camera()
        self._reset_camera()
        time.sleep(0.2)
        collected, img = self._collect_image(**kwargs)
        collected, img = self._collect_image(**kwargs)
        print(collected, img)
        if collected:
            print('collected image')
            measurement_img = img_as_ubyte(rgb2gray(img))
        else:
            self._reset_camera()
            self._reset_camera()
            print("trying to reset camera connection")
            collected, img = self._collect_image(**kwargs)
            collected, img = self._collect_image(**kwargs)
            if collected:
                measurement_img = img_as_ubyte(rgb2gray(img))
                print('success on retry')
            else:
                raise RuntimeError(
                    'Failed to collect camera image after two attempts. '
                    'Check that the camera is connected and the '
                    f"camera_interface ('{self.config['camera_interface']}') "
                    'settings are correct.'
                )

                raise RuntimeError(
                    'Failed to collect camera image after two attempts. '
                    'Check that the camera is connected and the '
                    f"camera_interface ('{self.config['camera_interface']}') "
                    'settings are correct.'
                )

        if set_empty:
            self.empty_img = measurement_img
            print('setting empty image', measurement_img)
            if self.data is not None and 'sample_uuid' in self.data:
                self.config['empty_uuid'] = copy.deepcopy(self.data['sample_uuid'])
            return self._build_dataset(
                name=name,
                turbidity_metric=1.0,
                measurement_img=measurement_img,
                empty_img=measurement_img,
                mask=np.ones_like(measurement_img, dtype=bool),
                cx=0,
                cy=0,
                empty_from_measurement=False,
                is_empty_reference=True,
            )
            if self.data is not None and 'sample_uuid' in self.data:
                self.config['empty_uuid'] = copy.deepcopy(self.data['sample_uuid'])
            return self._build_dataset(
                name=name,
                turbidity_metric=1.0,
                measurement_img=measurement_img,
                empty_img=measurement_img,
                mask=np.ones_like(measurement_img, dtype=bool),
                cx=0,
                cy=0,
                empty_from_measurement=False,
                is_empty_reference=True,
            )
        else:
            print('measuring turbidity')
            measurement_img = measurement_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]
        print('measurement image: ', measurement_img.shape, type(measurement_img))


        #empty SANS cell image for masking
        empty_img = None
        empty_from_measurement = False
        empty_img = None
        empty_from_measurement = False
        if self.empty_img is not None:
            empty_img = self.empty_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]
        elif self.config.get('empty_uuid'):
            if Eq is None:
                self.log_warning('Cannot load empty image without tiled. Using measurement image for mask.')
            elif self.data is None or not hasattr(self.data, 'tiled_client') or self.data.tiled_client is None:
                self.log_warning('No tiled client available. Using measurement image for mask.')
            else:
                tiled_result = self.data.tiled_client.search(Eq('sample_uuid', self.config['empty_uuid']))
                if len(tiled_result) == 0:
                    self.log_warning(f"No tiled entry found for empty_uuid={self.config['empty_uuid']}. Using measurement image for mask.")
                else:
                    item = tiled_result.items()[-1][-1]
                    try:
                        ds = item.read(optimize_wide_table=False)
                    except TypeError:
                        ds = item.read()
                    if 'img_MT' in ds:
                        empty_img = ds['img_MT'].values
                    elif 'img' in ds:
                        empty_img = ds['img'].values
                    if empty_img is not None:
                        empty_img = empty_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]
                tiled_result = self.data.tiled_client.search(Eq('sample_uuid', self.config['empty_uuid']))
                if len(tiled_result) == 0:
                    self.log_warning(f"No tiled entry found for empty_uuid={self.config['empty_uuid']}. Using measurement image for mask.")
                else:
                    item = tiled_result.items()[-1][-1]
                    try:
                        ds = item.read(optimize_wide_table=False)
                    except TypeError:
                        ds = item.read()
                    if 'img_MT' in ds:
                        empty_img = ds['img_MT'].values
                    elif 'img' in ds:
                        empty_img = ds['img'].values
                    if empty_img is not None:
                        empty_img = empty_img[row_crop[0]:row_crop[1], col_crop[0]:col_crop[1]]

        if empty_img is None:
            self.log_warning('No empty image available. Using measurement image for mask and normalization.')
            empty_img = measurement_img
            empty_from_measurement = True
        
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
        
        
        empty_intensity = empty_img[mask]
        filled_intensity = measurement_img[mask]
        
        pedestal = np.abs(np.min(empty_intensity))+1
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
        
        return self._build_dataset(
            name=name,
            turbidity_metric=turbidity_metric,
            measurement_img=measurement_img,
            empty_img=empty_img,
            mask=mask,
            cx=cx,
            cy=cy,
            empty_from_measurement=empty_from_measurement,
            is_empty_reference=False,
        )
        
        return self._build_dataset(
            name=name,
            turbidity_metric=turbidity_metric,
            measurement_img=measurement_img,
            empty_img=empty_img,
            mask=mask,
            cx=cx,
            cy=cy,
            empty_from_measurement=empty_from_measurement,
            is_empty_reference=False,
        )



_DEFAULT_CUSTOM_CONFIG = {
        '_classname': 'AFL.automation.instrument.OpticalTurbidity.OpticalTurbidity',
        '_args': [
            {'_classname': 'AFL.automation.instrument.NetworkCamera.NetworkCamera',
             '_args' : [
                 'http://afl-video:8081/103/current'
             ]
             }
        ]
}
_DEFAULT_CUSTOM_PORT = 5001
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
