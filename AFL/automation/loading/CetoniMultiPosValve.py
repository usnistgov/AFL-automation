from AFL.automation.loading.FlowSelector import FlowSelector

class CetoniMultiPosValve(FlowSelector):
    def __init__(self,parentpump,portlabels={}):
        '''
        connect to valve and query the number of positions

        parameters:
            port - string describing the serial port the actuator is connected to
            baud - baudrate to use
            portlabels - dict for smart port naming, of the form {'sample':3,'instrument':4,'rinse':5,'waste':6}
        '''
        self.app = None
        self.name = 'CetoniMultiPosValve'

        self.pump = parentpump.pump

        assert self.pump.has_valve(), "this pump does not have a valve installed"

        self.valve = self.pump.get_valve()
        self.npositions = self.valve.number_of_valve_positions()
        print("Valve positions: ", self.npositions)



        self.valve.switch_valve_to_position(0)

        self.portlabels = portlabels

        portnum = self.getPort()
        port = self.getPort(as_str=True)
        self.portString = f'{port}/{portnum}'

    def selectPort(self,port,direction=None):
        '''
            moves the selector to portnum

            if direction is set to either "CW" or "CCW" it moves the actuator in that direction.  
            if unset or other value, will move via most efficient route.

        '''
        if self.app is not None:
            self.app.logger.debug(f'Setting port to {port}')

        if type(port) is str:
            portnum = self.portlabels[port]
        else:
            portnum = int(port)

        assert portnum <= self.npositions, "That port doesn't exist."

        
        self.valve.switch_valve_to_position(portnum)

        self.portString = f'{port}/{portnum}'

    def getPort(self,as_str=False):
        '''
            query the current selected position
        '''
        portnum = self.valve.actual_valve_position()
                
        if not as_str:
            return portnum
        else:
            for label,port in self.portlabels.items():
                if port == portnum:
                    return label
            return None
