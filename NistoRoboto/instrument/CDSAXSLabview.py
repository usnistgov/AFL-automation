import win32com
import win32com.client
import pythoncom
import time
from NistoRoboto.APIServer.driver.Driver import Driver

class CDSAXSLabview(Driver):
    
    axis_name_to_id_lut = {
        'X-stage' : 0,
        'Z-stage' : 1,
        'Z-gonio' : 2,
        'Phi' : 3,
        'Theta' : 4,
        'Y-gonio' : 5,
        'Y-stage' : 6,
        'Beamstop-z': 7,
        'Beamstop-y': 8,
        'Tungsten-y': 9 ,
        'Detector-z': 10,
        'None': 11
    }
    
    axis_id_to_name_lut = {value:key for key, value in axis_name_to_id_lut.items()}
    
    def __init__(self,vi=r'C:\saxs_control\GIXD controls.vi'):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''

        self.app = None
        self.name = 'CDSAXSLabview'
        self.vi = vi
        
        pythoncom.CoInitialize()
        self.labview = win32com.client.dynamic.Dispatch("Labview.Application")

        self.main_vi = self.labview.getvireference(self.vi)

        self.main_vi.setcontrolvalue('Measurement',3) # 3 should bring the single Pilatus tab to the front

    def connect(self):
        self.labview = win32com.client.dynamic.Dispatch("Labview.Application")
        self.main_vi = self.labview.getvireference(self.vi)
        pythoncom.CoInitialize()
        
    @Driver.unqueued()        
    def getExposure(self):
        '''
            get the currently set exposure time

        '''
        self.connect()
        return self.main_vi.getcontrolvalue('Single Pilatus Parameters')[0]
    def getFilename(self):
        '''
            get the currently set file name

        '''
        self.connect()
        return self.main_vi.getcontrolvalue('Single Pilatus Parameters')[1]

    @Driver.unqueued()
    def printMainVi(self):
        self.connect()
        return str(self.main_vi)
    @Driver.unqueued()
    def printLabviewObj(self):
        self.connect()
        return str(self.labview)
    
    def setExposure(self,exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.connect()
        
        fileName = self.getFilename()

        self.main_vi.setcontrolvalue('Single Pilatus Parameters',(exposure,fileName))

    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')
        self.connect()
        if '\\' in name:
            raise ValueError('cannot have slashes in filename')
            
        exposure = self.getExposure()

        self.main_vi.setcontrolvalue('Single Pilatus Parameters',(exposure,name))


    def getPath(self):
        return self.main_vi.getcontrolvalue('FilePath')   # @TODO: fill in here
    
    @Driver.unqueued(render_hint='2d_img',log_image=True)
    def getData(self,**kwargs):
        self.connect()
        return self.main_vi.getcontrolvalue('Pilatus Data')

    def setPath(self,path):
        if self.app is not None:
            self.app.logger.debug(f'Setting file path to {path}')

        self.path = str(path)
        self.main_vi.setcontrolvalue('FilePath',path)
        
    @Driver.unqueued()  
    def getStatus(self):
        self.connect()
        return self.main_vi.getcontrolvalue('Process Status Message')
   
    @Driver.unqueued()  
    def getNScans(self):
        self.connect()
        return self.main_vi.getcontrolvalue('# of Scans')
        
    def setNScans(self,nscans):
        self.connect()
        self.main_vi.setcontrolvalue('# of Scans',nscans)
    
    @Driver.unqueued()  
    def getSweepAxis(self):
        self.connect()
        return self.axis_id_to_name_lut[self.main_vi.getcontrolvalue('Sweep Axis')]
    def setSweepAxis(self,axis):
        if type(axis)=='str':
            axis=self.axis_name_to_id_lut[axis]
        self.connect()
        self.main_vi.setcontrolvalue('Sweep Axis',axis) # this is an enum, 6 is Y-stage
    
    @Driver.unqueued()  
    def getYStagePos(self):
        self.connect()
        return self.main_vi.getcontrolvalue('Y-stage')
    @Driver.unqueued()  
    def getZStagePos(self):
        self.connect()
        return self.main_vi.getcontrolvalue('Z-stage')
    @Driver.unqueued()  
    def getXStagePos(self):
        self.connect()
        return self.main_vi.getcontrolvalue('X-Stage')
    
    
    def setSweepStart(self,start):
        self.connect()
        self.main_vi.setcontrolvalue('Start Value',start)
        
    @Driver.unqueued()  
    def getSweepStart(self):
        self.connect()
        return self.main_vi.getcontrolvalue('Start Value')
    
    def setSweepStep(self,step):
        self.connect()
        self.main_vi.setcontrolvalue('Step',step)
    
    @Driver.unqueued()  
    def getSweepStep(self):
        self.connect()
        return self.main_vi.getcontrolvalue('Step')
        
    def expose(self,name=None,exposure=None,block=False):
        self.connect()
        if name is not None:
            self.setFilename(name)
        else:
            name=self.getFilename()

        if exposure is not None:
            self.setExposure(exposure)
        else:
            exposure=self.getExposure()

        self.setNScans(1)
        self.setSweepAxis('None')
        
            
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')

        self.main_vi.setcontrolvalue('Expose Pilatus',True)
        time.sleep(0.5)
        if block:
            while(self.getStatus() != 'Success'):
                time.sleep(0.1)
                
    def scan(self,axis,npts,start,step,name=None,exposure=None,block=False):
        self.connect()
        if name is not None:
            self.setFilename(name)
        else:
            name=self.getFilename()

        if exposure is not None:
            self.setExposure(exposure)
        else:
            exposure=self.getExposure()

        self.setNScans(npts)
        self.setSweepAxis(axis)
        self.setSweepStart(start)
        self.setSweepStep(step)
            
        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')

        self.main_vi.setcontrolvalue('Expose Pilatus',True)
        time.sleep(0.5)
        if block:
            while(self.getStatus() != 'Success'):
                time.sleep(0.1)