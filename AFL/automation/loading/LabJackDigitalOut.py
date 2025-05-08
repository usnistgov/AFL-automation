import lazy_loader as lazy
ljm = lazy.load("labjack.ljm", require="AFL-automation[labjack]")

from AFL.automation.loading.Sensor import Sensor
import time

class LabJackDigitalOut():# xxx todo: generic digitalout class?Sensor):
    def __init__(self,devicetype="ANY",connection="ANY",deviceident="ANY",port_to_write="DAC0",polling_rate=200,shared_device=None,intermittent_device_handle=False):
        '''
    	Initialize a LabJack connection
    	
    	Params:
    	
    	devicetype (str): series/type of LJ to connect to "T4" "T7" etc.
    	connection (str): "ANY", "USB", "TCP", "ETHERNET", or "WIFI"
    	deviceident (str): serial number OR IP OR device name OR "ANY"
    	port_to_write (str): LabJack port for device
        shared_device (LabJack class): device to share the handle of
        intermittent_device_handle (bool): if True, closes the device on each communication.  not compatible with shared_device
        
        '''
        #if not intermittent_device_handle:
        if shared_device is not None:
            self.device_handle = shared_device.device_handle
        else:
            self.device_handle = ljm.openS(devicetype, connection, deviceident)
        self.devicetype = devicetype
        self.connection = connection
        self.deviceident = deviceident
        self.intermittent_device_handle = intermittent_device_handle
        self.shared_device = shared_device
        self.port_to_write = port_to_write
        self.intervalHandle = 0
        #ljm.startInterval(self.intervalHandle, polling_rate)
    
    #def __del__(self):
        
    def write(self,val):
        numSkippedIntervals = ljm.waitForNextInterval(self.intervalHandle)
        #if self.intermittent_device_handle:
        #    self.device_handle = ljm.openS(self.devicetype, self.connection, self.deviceident)
        result = ljm.eWriteName(self.device_handle, self.port_to_write,val)
        #if self.intermittent_device_handle:
        #    ljm.close(self.device_handle)
        return result
    def __str__(self):
        #if self.intermittent_device_handle:
        #    self.device_handle = ljm.openS(self.devicetype, self.connection, self.deviceident)
        info = ljm.getHandleInfo(self.device_handle)
        #if self.intermittent_device_handle:
        #    ljm.close(self.device_handle)
        return f"LabJack with Device type: %{info[0]}, Connection type: {info[1]}, Serial number: {info[2]}, IP address: {ljm.numberToIP(info[3])}, Port: {info[4]}, Max bytes per MB: {info[5]}"
        
