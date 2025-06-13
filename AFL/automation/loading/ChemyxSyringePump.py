'''

This is largely duplicated from the reference code provided by Chemyx.  
Their package is a GUI and direct import of the module would be problematic.

'''

from AFL.automation.loading.SyringePump import SyringePump

import sys

import serial
import serial.tools.list_ports
import sys
import glob

import time
import datetime
class ChemyxSyringePump(SyringePump):

    def __init__(self,port,syringe_id_mm,syringe_volume,baud=9600,flow_delay=5):
        '''
          Initializes and verifies connection to a Chemyx syringe pump.

            port = serial port reference

            syringe_id_mm = syringe inner diameter in mm, used for absolute volume. 
                            (will re-program the pump with this diameter on connection)

            syringe_volume = syringe volume in mL

            baud = baudrate for connection
        '''

        self.app = None
        self.name = 'ChemyxSyringePump'
        self.flow_delay = flow_delay

        self.pump = ChemyxConnection(port,baud)
        self.pump.openConnection()

        #syringe = self.pump.get_syringe_param()
        self.syringe_id_mm = self.getValueFromParams('dia')
        #self.piston_stroke_mm = syringe.max_piston_stroke_mm

        #self.pump.set_volume_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres)
        #self.pump.set_flow_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres, 
        #    qmixpump.TimeUnit.per_minute)


        self.syringe_volume_ml = self.getValueFromParams('volume') #this may not be a real attribute

        param_limits = self.pump.getParameterLimits()[1].split(' ')
        self.max_rate = float(param_limits[0])
        self.min_rate = float(param_limits[1])
        self.max_volume = float(param_limits[2])
        self.min_volume = float(param_limits[3])
        print(f'Currently loaded syringe is a {self.syringe_volume_ml}, max pump rate {self.max_rate}, ID {self.syringe_id_mm}')


    def __del__(self):
        pass


    def wait_dosage_finished(self, timeout_seconds=60):
        """
        The function waits until the last dosage command has finished
        until the timeout occurs.
        """
        start_time = datetime.datetime.now()
        timeout = datetime.timedelta(seconds=timeout_seconds)
        exit = False
        while (not exit and (datetime.datetime.now()-start_time)<timeout):
            exit = not self.getStatus() # False if stopped -> exit = True =
            time.sleep(0.05)

    def stop(self):
        '''
        Abort the current dispense/withdraw action. 
        '''

        self.pump.stopPump()

    def withdraw(self,volume,block=True,delay=True):
        self.pump.stopPump()
        rate = self.getRate()
        expected_duration = volume / rate * 60 # anticipated duration of pump move in s

        timeout = expected_duration + 30

        timeout = max((timeout),30) # in case things get really weird.
        if self.app is not None:
            self.app.logger.debug(f'Withdrawing {volume}mL at {rate} mL/min, expected to take {expected_duration} s')

        #if (self.getLevel()+volume) > self.max_volume:
        #    self.app.logger.warn(f'Requested withdrawal of {volume} but current level is {self.getLevel()} of a max {self.max_volume}.  Moving to {self.max_volume}')
        #    self.setLevel(self.max_volume)

        self.pump.setVolume(-float(volume))
        self.pump.startPump()        
        self.pump.startPump()
        if block:
            self.wait_dosage_finished(timeout)
        if delay:
            time.sleep(self.flow_delay)

    def dispense(self,volume,block=True,delay=True):
        self.pump.stopPump()
        rate = self.getRate()
        expected_duration = volume / rate * 60 # anticipated duration of pump move in s

        timeout = expected_duration + 30

        timeout = max((timeout),30) # in case things get really weird.
        if self.app is not None:
            self.app.logger.debug(f'Withdrawing {volume}mL at {rate} mL/min, expected to take {expected_duration} s')

        #if (self.getLevel()-volume) < 0:
        #    self.app.logger.warn(f'Requested dispense of {volume} but current level is {self.getLevel()} .  Moving to 0')
        #    self.setLevel(self.max_volume)

        self.pump.setVolume(float(volume))
        self.pump.startPump()
        self.pump.startPump()
        if block:
            self.wait_dosage_finished(timeout)
        if delay:
            time.sleep(self.flow_delay)
        


    def setRate(self,rate): #@TODO
        if self.app is not None:
            self.app.logger.debug(f'Setting pump rate to {rate} mL/min')
        self.pump.setRate(rate)

    def getRate(self): #@TODO
        return self.getValueFromParams('rate')

    def emptySyringe(self):
        self.setLevel(0)

    def getLevel(self):
        return float(self.pump.getDisplacedVolume()[1].split(' = ')[1])
        #self.assertAlmostEqual(max_volume, fill_level_is)

    def setLevel(self,level):
        self.pump.dispense(self.getLevel()-level)

    def blockUntilStatusStopped(self,pollingdelay=0.2):
        '''
        This is a deprecated function from old serial logic.  It should work, but do not use.
        '''
        self.wait_dosage_finished(30)


    def getStatus(self): #@TODO
        '''
        query the pump status and return whether the pump is moving or not (true if moving, false if stopped)
        '''

        status = self.pump.getPumpStatus()[1]
        if int(status)==4:
            raise Exception('Pump stalled or other error!')
        return bool(int(status))

    def getValueFromParams(self,search_key):
        params = self.pump.getParameters()
        for entry in params:
            try:
                key,val = entry.split(' = ')
                if key == search_key:
                    return float(val)
            except ValueError as e:
                pass


def getOpenPorts():
    # portinfo = []
    # for port in serial.tools.list_ports.comports():
    #     if port[2] != 'n/a':
    #         info = [port.device, port.name, port.description, port.hwid]
    #         portinfo.append(info)
    # return portinfo

    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')
    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
            #print(port)
        except (OSError, serial.SerialException):
            pass
    #print(result)
    return result

def parsePortName(portinfo):
    """
    On macOS and Linux, selects only usbserial options and parses the 8 character serial number.
    """
    portlist = []
    for port in portinfo:
        if sys.platform.startswith('win'):
            portlist.append(port[0])
        elif sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
            if 'usbserial' in port[0]:
                namelist = port[0].split('-')
                portlist.append(namelist[-1])
    return portlist

class ChemyxConnection(object):
    def __init__(self, port, baudrate, x = 0, mode = 0, verbose=False):
        self.port = port
        self.baudrate = baudrate
        self.x = x
        self.mode = mode
        self.verbose = verbose

    def openConnection(self):
        try:
            self.ser = serial.Serial()
            self.ser.baudrate = self.baudrate
            self.ser.port = self.port
            self.ser.timeout = 0
            self.ser.open()
            if self.ser.isOpen():
                if self.verbose:
                    print("Opened port")
                    print(self.ser)
                self.getPumpStatus()
                self.ser.flushInput()
                self.ser.flushOutput()
        except Exception as e:
            if self.verbose:
                print('Failed to connect to pump')
                print(e)
            pass

    def closeConnection(self):
        self.ser.close()
        if self.verbose:
            print("Closed connection")

    def sendCommand(self, command):
        try:
            arg = bytes(str(command), 'utf8') + b'\r'
            if self.verbose:
                print(f' wrote : {arg}')
            self.ser.write(arg)
            time.sleep(0.5)
            response = self.getResponse()
            if self.verbose:
                print(f'   response: {response}')
            return response
        except TypeError as e:
            if self.verbose:
                print(e)
            self.ser.close()

    def getResponse(self):
        try:
            response_list = []
            while True:
                response = self.ser.readlines()
                for line in response:
                    line = line.strip(b'\n').decode('utf8')
                    line = line.strip('\r')
                    if self.verbose:
                        print(line)
                    response_list.append(line)
                break
            return response_list
        except TypeError as e:
            if self.verbose:
                print(e)
            self.closeConnection()
        except Exception as f:
            if self.verbose:
                print(f)
            self.closeConnection()

    def startPump(self):
        command = 'start'
        command = self.addX(command)
        command = self.addMode(command)
        response = self.sendCommand(command)
        if(self.verbose):
            print('sent start command')
        return response

    def stopPump(self):
        command = 'stop'
        command = self.addX(command)
        response = self.sendCommand(command)
        return response

    def pausePump(self):
        command = 'pause'
        command = self.addX(command)
        response = self.sendCommand(command)
        return response

    def restartPump(self):
        command = 'restart'
        response = self.sendCommand(command)
        return response

    def setUnits(self, units):
        units_dict = {'mL/min': '0', 'mL/hr': '1', 'μL/min': '2', 'μL/hr': 3}
        command = 'set units ' + str(units_dict[units])
        response = self.sendCommand(command)
        return response

    def setDiameter(self, diameter):
        command = 'set diameter ' + str(diameter)
        response = self.sendCommand(command)
        return response

    def setRate(self, rate):
        command = 'set rate ' + str(rate)
        response = self.sendCommand(command)
        return response

    def setVolume(self, volume):
        command = 'set volume ' + str(volume)
        response = self.sendCommand(command)
        return response

    def setDelay(self, delay):
        command = 'set delay ' + str(delay)
        response = self.sendCommand(command)
        return response

    def setTime(self, timer):
        command = 'set time ' + str(timer)
        response = self.sendCommand(command)
        return response

    def getParameterLimits(self):
        command = 'read limit parameter'
        response = self.sendCommand(command)
        return response

    def getParameters(self):
        command = 'view parameter'
        response = self.sendCommand(command)
        return response

    def getDisplacedVolume(self):
        command = 'dispensed volume'
        response = self.sendCommand(command)
        return response

    def getElapsedTime(self):
        command = 'elapsed time'
        response = self.sendCommand(command)
        return response

    def getPumpStatus(self):
        command = 'pump status'
        response = self.sendCommand(command)
        return response
    def addMode(self, command):
        if self.mode == 0:
            return command
        else:
            return command + ' ' + str(self.mode - 1)

    def addX(self, command):
        if self.x == 0:
            return command
        else:
            return str(self.x) + ' ' + command


