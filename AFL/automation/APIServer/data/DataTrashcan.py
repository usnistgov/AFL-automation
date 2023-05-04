from .DataPacket import DataPacket

class DataTrashcan(DataPacket):
    '''
      A DataPacket implementation *for testing only* that takes all its data and simply throws it away.
    '''
    def transmit(self):
        pass
