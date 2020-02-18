from NistoRoboto.shared.utilities import listify
from NistoRoboto.DeviceServer.Protocol import Protocol
from math import ceil,sqrt
import subprocess,shlex

class SpecScreenProtocol(Protocol):
    def __init__(self):
        self.app = None
        self.name = 'SpecScreenProtocol'
        
    def execute(self,**kwargs):
        if 'spec_cmd' not in kwargs:
            raise ValueError('No spec_cmd specified!')
        spec_cmd = kwargs['spec_cmd']
        subprocess.call(shlex.split(f'screen -X stuff "{spec_cmd}\n"'))





   
