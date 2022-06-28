class Sensor():
    def __init__(self,address=1,channel=0):
        raise NotImplementedError
        
    def calibrate(self):
        raise NotImplementedError
        
    def read(self):
        raise NotImplementedError
