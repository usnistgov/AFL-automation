import lazy_loader as lazy
DAQC2plate = lazy.load("piplates.DAQC2plate", require="AFL-automation[piplates]")
GPIO = lazy.load("RPi.GPIO", require="AFL-automation[rpi-gpio]")

from AFL.automation.loading.Sensor import Sensor

class DACQC2Sensor(Sensor):
    def __init__(self,address=1,channel=0):
        self.address = 1
        self.channel = 0
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17,GPIO.OUT)
        GPIO.output(17,1)#set 17 to line-high to reduce noise
        
    def calibrate(self):
        GPIO.output(17,0)
        time.sleep(0.1)
        GPIO.output(17,1)
        
    def read(self):
        for i in range(100):
            try:
                value = DAQC2plate.getADC(self.address,self.channel)
            except IndexError:
                pass
            else:
                return value
        raise ValueError
