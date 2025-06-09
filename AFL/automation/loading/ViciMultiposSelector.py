from AFL.automation.loading.FlowSelector import FlowSelector
from AFL.automation.loading.SerialDevice import SerialDevice
import lazy_loader as lazy
serial = lazy.load("serial", require="AFL-automation[serial]")
import time

class ViciMultiposSelector(SerialDevice,FlowSelector):
    def __init__(self,port,baudrate=9600,portlabels=None):
        '''
        connect to valve and query the number of positions

        parameters:
            port - string describing the serial port the actuator is connected to
            baud - baudrate to use
            portlabels - dict for smart port naming, of the form {'sample':3,'instrument':4,'rinse':5,'waste':6}
        '''
        self.app = None
        self.name = 'ViciMultiPosSelector'

        super().__init__(port,baudrate=baudrate,timeout=0.5)

        response = self.sendCommand('NP\x0D')[2:4]
        
        assert response != '', "Did not get a reply from the selector... is the port, baudrate correct?  Is it turned on and plugged in?"
        
        self.npositions = int(response)

        self.portlabels = portlabels

        portnum = self.getPort()
        port = self.getPort(as_str=True)
        self.portString = f'{port}/{portnum}'

    def selectPort(self,port,direction=None,block=True):
        '''
            moves the selector to portnum

            if direction is set to either "CW" or "CCW" it moves the actuator in that direction.  
            if unset or other value, will move via most efficient route.

            Parameters
            ------------
            port : String or int
                the name, or number, of the port to switch to
            direction : String, default=None
                direction "CW" or "CCW" to perform the move in
            block : bool, default=True
                block return until move completes
        '''
        if self.app is not None:
            self.app.logger.debug(f'Setting port to {port}')

        if type(port) is str:
            portnum = self.portlabels[port]
        else:
            portnum = int(port)

        assert portnum <= self.npositions, "That port doesn't exist."

        if direction=="CCW":
            readback = self.sendCommand('CC%02i\x0D'%portnum,response=False)
        elif direction== "CW":
            readback = self.sendCommand('CW%02i\x0D'%portnum,response=False)
        else:
            readback = self.sendCommand('GO%02i\x0D'%portnum,response=False)

        if block:
            while self.getPort() != portnum:
                time.sleep(0.1)

        self.portString = f'{port}/{portnum}'

    def getPort(self,as_str=False):
        '''
            query the current selected position
        '''
        portnum = int(self.sendCommand('CP\x0D')[2:4])
                
        if not as_str:
            return portnum
        else:
            for label,port in self.portlabels.items():
                if port == portnum:
                    return label
            return None
