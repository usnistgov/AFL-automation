import numpy as np
import pyspec.client.SpecConnection import SpecConnection
import pyspec.client.SpecCounter import SpecCounter
import sys
import time


class PySpecClient():
    """
    This class will interact with the spec server on the hutch IDB3 computer and allow SARA pass the appropriate commands
    """
    def __init__(self, address='id3b.classe.cornell.edu', port='spec'):
        self.address = address
        self.port = port
        self.connected = False        
        self.output = []
        self.last_output = None
        self.counter = {}

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

        self.spec = SpecConnection(self.conn) #hard coded connection
        while not self.spec.is_connected():
            pass

        if self.spec.is_connected():
            print(f'established connection to {self.conn}')
        
        #need to register our desired channels:
        self.spec.register('status/ready',self._update_channel) #this channel can be read as if spec is busy or not??
        self.spec.register('output/tty',self._update_output) #this channel returns the output from the cmd line and passes it into the output list
        print('List of registered channels')
        for ch in list(self.spec.reg_channels):
            print(ch)
        print("")
        return

    def run_cmd(self,cmd):
        self.spec.run_cmd(cmd)

    def cd(self, path):
        """ A generic mv command. Moves the Spec directory to the specified path
        """

        self.spec.run_cmd(f'cd {path}')

    def mkdir(self, path):
        """A generic mkdir command. makes the specified directory or set of directories """
        self.spec.run_cmd(f'u mkdir {path}')

    def register_counter(self,name):
        self.counter[name] = SpecCounter(name,self.conn)



