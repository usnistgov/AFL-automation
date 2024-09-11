from AFL.automation.APIServer.Driver import Driver
import serial

class TemperatureDeck(Driver):

    defaults = {}
    defaults['serial_port'] = '/dev/ttyACM0'
    def __init__(self,overrides=None):
        self.app = None
        Driver.__init__(self,name='TemperatureDeck',defaults=self.gather_defaults(),overrides=overrides)
        self.name = 'TemperatureDeck'

    def set_temp(self,sp):
        with serial.Serial(self.config['serial_port'],115200) as p:
            p.write(f'M104 S{str(int(sp)).zfill(2)}\r\n'.encode())
            ret1 = p.readline()
            ret2 = p.readline()
            if 'ok' not in ret1.decode('UTF-8'):
                raise ValueError(f'Error: {ret1}')
    def status(self):
        temp = self.read_temp()
        return [f'setpoint: {temp[0]}',f'readback: {temp[1]}']
    
    def read_temp(self):
        with serial.Serial(self.config['serial_port'],115200) as p:
            p.write(f'M105\r\n'.encode())
            ret1 = p.readline()
            setpoint = float(ret1[2:6])
            readback = float(ret1[10:14])
            ret2 = p.readline()
        return (setpoint,readback)
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
