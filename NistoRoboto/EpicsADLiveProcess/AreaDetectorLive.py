import epics
import numpy as np
import queue


class AreaDetectorLive():
    def __init__(self,basepv="13SIM1:",cam="cam1:",filewriter="TIFF1:",image="image1:"):
        self.imgqueue = queue.Queue()
        
        self.size_x = epics.caget(basepv+cam+"ArraySizeX_RBV")
        self.size_y = epics.caget(basepv+cam+"ArraySizeY_RBV")
        
        self.det_model = epics.caget(basepv+cam+"Model_RBV")
        self.det_mfgr = epics.caget(basepv+cam+"Manufacturer_RBV")
        
        self.filename = "notset"
        self.expt = 0
        self.arraydata = None
        
        self.PVimagearray = epics.PV(basepv+image+"ArrayData",callback=self.cbfunc,auto_monitor=True)
        self.PVfilename = epics.PV(basepv+filewriter+"FileName",callback=self.cbfunc,auto_monitor=True)
        self.PVexpt = epics.PV(basepv+cam+"AcquireTime",callback=self.cbfunc,auto_monitor=True)
        
        #@TODO: this could track all the metadata in, e.g., the HDF5 filewriter, and might need to for complex experiments.  For now this is probably fine.

        print(f'Connected to a {self.det_mfgr} {self.det_model}, {self.size_x} x {self.size_y}')
        
    def cbfunc(self,pvname=None,value=None,char_value=None,**kwargs):
        self.imgqueue.put((pvname,value))
    
    def queuehandler(self):
        data = self.imgqueue.get(block=True,timeout=None)
        if(data[0] == self.PVfilename.pvname):
            self.filename = data[1].tobytes().decode('ascii')
            return None
        elif(data[0] == self.PVexpt.pvname):
            self.expt = data[1]
            return None
        elif(data[0] == self.PVimagearray.pvname):
            if(len(data[1])>0):
                self.arraydata = np.reshape(data[1],(self.size_x,self.size_y))
                return (self.filename,self.expt,self.arraydata)
            return None
        else:
            raise NotImplementedError
    
    def status(self):
        print(f'Last filename: {self.filename}')
        print(f'Last exposure: {self.expt}')
        print(f'Queue contains {self.imgqueue.qsize()} unprocessed items')