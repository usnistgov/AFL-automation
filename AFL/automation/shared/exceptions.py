class EmptyException(Exception):
    '''Raised when a mixture runs out of mass or volume'''
    pass

class MixingException(Exception):
    '''Raised when a mixture cannot be made'''
    pass

class SerialCommsException(Exception):
    '''Raised when the system receives a serial response it can't parse, likely a garbled line'''
    pass

class NoDeviceFoundException(Exception):
    '''Raised when no matching device can be found on the selected port'''
    pass

class NotFoundError(Exception):
    pass
