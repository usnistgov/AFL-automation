class SyringePump():

    def stop(self):
        raise NotImplementedError

    def withdraw(self,volume,block=True):
        raise NotImplementedError

    def dispense(self,volume,block=True):
        raise NotImplementedError
        
    def setRate(self,rate):
        raise NotImplementedError

    def getRate(self,rate):
        raise NotImplementedError