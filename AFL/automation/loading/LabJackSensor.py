import lazy_loader as lazy

from AFL.automation.loading.Sensor import Sensor
import time



class LabJackSensor(Sensor):
    def __init__(self,devicetype="ANY",connection="ANY",deviceident="ANY",port_to_read="AIN0",reset_port="DIO5",polling_rate=200,intermittent_device_handle=False):
        '''
    	Initialize a LabJack connection
    	
    	Params:
    	
    	devicetype (str): series/type of LJ to connect to "T4" "T7" etc.
    	connection (str): "ANY", "USB", "TCP", "ETHERNET", or "WIFI"
    	deviceident (str): serial number OR IP OR device name OR "ANY"
    	port_to_read (str): LabJack port for device
        '''
        # Lazy-load the labjack optional dependency
        self.ljm = lazy.load("labjack.ljm", require="AFL-automation[labjack]")

        self.fio = reset_port
        self.device_handle = self.ljm.openS(devicetype, connection, deviceident)
        self.port_to_read = port_to_read
        self.devicetype = devicetype
        self.connection = connection
        self.deviceident = deviceident
        self.intervalHandle = 0
        self.intermittent_device_handle = intermittent_device_handle
        self.ljm.startInterval(self.intervalHandle, polling_rate)
        self.ljm.eWriteName(self.device_handle,self.fio,1)#set physical FIO6 / logical DIO6 to TTL-hi
        # if self.intermittent_device_handle:
        #     ljm.close(self.device_handle)

    # def __del__(self):
    # 	ljm.close(self.device_handle)

    	
    def calibrate(self):
        self.ljm.eWriteName(self.device_handle,self.fio,0)
        time.sleep(0.2)
        self.ljm.eWriteName(self.device_handle,self.fio,1)
        # if self.intermittent_device_handle:
        #     ljm.close(self.device_handle)
        #
    def read(self):
        numSkippedIntervals = self.ljm.waitForNextInterval(self.intervalHandle)
        result = self.ljm.eReadName(self.device_handle, self.port_to_read)
        # if self.intermittent_device_handle:
        #     ljm.close(self.device_handle)
        return result 
    def __str__(self):
        info = self.ljm.getHandleInfo(self.device_handle)
        return f"LabJack with Device type: %{info[0]}, Connection type: {info[1]}, Serial number: {info[2]}, IP address: {self.ljm.numberToIP(info[3])}, Port: {info[4]}, Max bytes per MB: {info[5]}"
