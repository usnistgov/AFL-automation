class DataPacket:

    def __init__(self):
        self._dict = {}
        
        
    def __getitem__(self,key):
        return self._dict[key]
    
    def __setitem__(self,key,value):
        self._dict[key] = value
    
    def setupDefaults(self):
   
    def finalizeData(self):
        raise NotImplementedError
        
    def transmitData(self):
        raise NotImplementedError
