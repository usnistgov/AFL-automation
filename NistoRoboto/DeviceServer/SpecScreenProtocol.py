from NistoRoboto.shared.utilities import listify
from NistoRoboto.DeviceServer.Protocol import Protocol
from math import ceil,sqrt
import subprocess,shlex

class SpecScreenProtocol(Protocol):
    def __init__(self,log_file=None):
        self.app = None
        self.name = 'SpecScreenProtocol'
        self.log_file = log_file
        self.n_spec_blocks=3

    def status(self):
        status = []
        if self.log_file is not None:
            f = subprocess.Popen(shlex.split('tail -n 1000 {self.log_file}'),stdout=subprocess.PIPE,stderr=subprocess.PIPE)

            lines = []
            spec_lines = []
            for i,line in enumerate(f.stdout.readline()):
                lines.append(line)
                if 'SPEC' in line:
                    spec_lines.append(i)

            
            spec_lines = spec_lines[::-1]
            for i in range(self.n_spec_blocks): 
                try:
                    m = spec_lines[i]
                    n = spec_lines[i+1]
                except IndexError:
                    break
                status.append('\n'.join(lines[m:n]))
            status = status[::-1]

        return status
        
    def execute(self,**kwargs):
        if 'spec_cmd' not in kwargs:
            raise ValueError('No spec_cmd specified!')
        spec_cmd = kwargs['spec_cmd']
        subprocess.call(shlex.split(f'screen -X stuff "{spec_cmd}\n"'))





   
