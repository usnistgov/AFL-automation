import lazy_loader as lazy
from AFL.automation.loading.Sensor import Sensor

class DACQC2Sensor(Sensor):
    def __init__(self,address=1,channel=0):
        self.address = 1
        self.channel = 0
        self.GPIO = lazy.load("RPi.GPIO", require="AFL-automation[rpi-gpio]")
        self.DAQC2plate = lazy.load("piplates.DAQC2plate", require="AFL-automation[piplates]")

        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setup(17,self.GPIO.OUT)
        self.GPIO.output(17,1)#set 17 to line-high to reduce noise
        
    def calibrate(self):
        self.GPIO.output(17,0)
        time.sleep(0.1)
        self.GPIO.output(17,1)
        
    def read(self):
        for i in range(100):
            try:
                value = self.DAQC2plate.getADC(self.address,self.channel)
            except IndexError:
                pass
            else:
                return value
        raise ValueError
