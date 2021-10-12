import numpy as np
import pyspec.client.SpecConnectionsManager as SCM
import sys
import time


class PySpecClient():
    """
    This class will interact with the spec server on the hutch IDB3 computer and allow SARA pass the appropriate commands

    ConnectToServer()                 Creates the spec connection from sara to the spec server
    SetFilePaths(path,filename2D)     Creates the directory structure and moves to the proper location. sends newfile cmd to spec
    SetFlyScan()                     Sets up flyscan cmd and arms the detector for XRD collection

    """
    def __init__(self, address='id3b.classe.cornell.edu', port='spec'):
        self.address = address
        self.port = port
        self.connected = False        
        self.output = []
        self.last_output = None

    def _update_output(self, value, channel):
        self.output.append(value)
        self.last_output = self.output[-1]
        print(self.last_output)
        

    def _update_channel(self, value, channel):
        print(f"{channel}: {value}")


    def connect(self):
        '''
        Connect to the external spec server at connection name conn.
        This should be an object that can be passed to the other functions that talk to a spec server
        '''
        self.conn = f'{self.address}:{self.port}'
        print('')
        print(self.conn)

        self.Spec = SCM.SpecConnection.SpecConnection(self.conn) #hard coded connection
        while not self.Spec.is_connected():
            pass

        if self.Spec.is_connected():
            print(f'established connection to {self.conn}')
        
        #need to register our desired channels:
        self.Spec.register('status/ready',self._update_channel) #this channel can be read as if spec is busy or not??
        self.Spec.register('output/tty',self._update_output) #this channel returns the output from the cmd line and passes it into the output list
        print('List of registered channels')
        for ch in list(self.Spec.reg_channels):
            print(ch)
        print("")
        return

    def run_cmd(self,cmd):
        self.spec.run_cmd(cmd)

    def cd(self, path):
        """ A generic mv command. Moves the Spec directory to the specified path
        """

        self.Spec.run_cmd(f'cd {path}')

    def mkdir(self, path):
        """A generic mkdir command. makes the specified directory or set of directories """
        self.Spec.run_cmd(f'u mkdir {path}')

    def get_detector_status(self):
        """Will output to the cmd line the status of the detector"""
        self.queryDetOut_cmd = "p epics_get('EIG1:cam1:DetectorState_RBV')"
        self.Spec.run_cmd(self.queryDetOut_cmd, timeout=60)
        self.last_output = self.Spec.reg_channels['output/tty'].read()
        return self.last_output

    def GetTimeToFill(self):
        """Returns the time in seconds until beam refill at chess"""
        self.queryTTF_cmd = "p epics_get('cesr_run_left')"
        self.Spec.run_cmd(self.queryTTF_cmd)
        self.last_output = self.Spec.reg_channels['output/tty'].read()
        return self.last_output

    def GetIntensity(self):
        self.queryIC_low = "p epics_get('ID3B_CNT04_VLT')"
        self.queryIC_high = "p epics_get('ID3B_CNT04_VLT')"
        self.Spec.run_cmd(self.queryIC_low)

        iclow = self.Spec.reg_channels['output/tty'].read()
        self.Spec.run_cmd(self.queryIC_high)
        self.last_output = self.Spec.reg_channels['output/tty'].read()
        ichigh = self.Spec.reg_channels['output/tty'].read()
        return iclow




