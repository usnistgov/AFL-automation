import win32com
import win32com.client


class CDSAXSLabview():
    def __init__(self,vi=r'C:\saxs_control\GIXD controls.vi'):
        '''
        connect to locally running labview vi with win32com and 

        parameters:
            vi: (str) the path to the LabView virtual instrument file for the main interface

        '''

        self.app = None
        self.name = 'CDSAXSLabview'

        self.labview = win32com.client.dynamic.Dispatch("Labview.Application")

        self.main_vi = labview.getvireference(vi)

        self.main_vi.setcontrolvalue('Measurement',3) # 3 should bring the single Pilatus tab to the front

    def getExposure(self):
        '''
            get the currently set exposure time

        '''
        return self.main_vi.getcontrolvalue('Single Pilatus Parameters')[0]
    def getFilename(self):
        '''
            get the currently set file name

        '''
        return self.main_vi.getcontrolvalue('Single Pilatus Parameters')[1]


    def setExposure(self,exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')

        fileName = self.getFilename()

        self.main_vi.setcontrolvalue('Single Pilatus Parameters',(exposure,fileName))

    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        exposure = self.getExposure()

        self.main_vi.setcontrolvalue('Single Pilatus Parameters',(exposure,name))


    def getPath(self):
        self.path = self.main_vi.getcontrolvalue('FilePath') # @TODO: fill in here



    def setPath(self,path):
        if self.app is not None:
            self.app.logger.debug(f'Setting file path to {path}')

        self.path = (str)path
        self.main_vi.setcontrolvalue('FilePath',path)
    

    def expose(self,name=None,exposure=None):
        if name is not None:
            self.setFilename(name)
        else:
            name=self.getFilename()

        if exposure is not None:
            self.setExposure(exposure)
        else:
            exposure=self.getExposure()

        if self.app is not None:
            self.app.logger.debug(f'Starting exposure with name {name} for {exposure} s')

        self.main_vi.setcontrolvalue('Expose Pilatus',True)

                
