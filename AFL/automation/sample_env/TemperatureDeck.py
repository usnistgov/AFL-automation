from AFL.automation.APIServer.Driver import Driver
import lazy_loader as lazy
serial = lazy.load("serial", require="AFL-automation[serial]")
import time
class TemperatureDeck(Driver):

    defaults = {}
    defaults['serial_port'] = '/dev/ttyACM0'
    defaults['temperature_move_timeout'] = 900
    defaults['temperature_move_sleep'] = 0.2

    def __init__(self,overrides=None):
        self.app = None
        Driver.__init__(self,name='TemperatureDeck',defaults=self.gather_defaults(),overrides=overrides)
        self.name = 'TemperatureDeck'
        self.cached_setpoint = None
        self.cached_readback = None
        self.cached_time = None
        self.read_temp()
    def set_temp(self,sp):
        with serial.Serial(self.config['serial_port'],115200) as p:
            p.write(f'M104 S{str(int(sp)).zfill(2)}\r\n'.encode())
            ret1 = p.readline()
            ret2 = p.readline()
            if 'ok' not in ret1.decode('UTF-8'):
                raise ValueError(f'Error: {ret1}')
    
    def move_temp(self,temperature,wait = 30,tolerance = 0.1):
        self.set_temp(temperature)
        start_time = time.time()
        while abs(self.read_temp()[1] - temperature) > tolerance and (time.time() - start_time) < self.config['temperature_move_timeout']:
            time.sleep(self.config['temperature_move_sleep'])
        time.sleep(wait)

    def status(self):
        temp = self.read_temp()
        return [f'setpoint: {temp[0]}',f'readback: {temp[1]}']
    
    def read_temp(self):
        if self.cached_time is not None:
            if (time.time() - self.cached_time) < 0.1:
                return (self.cached_setpoint,self.cached_readback)
        try:
            with serial.Serial(self.config['serial_port'],115200) as p:
                p.write(f'M105\r\n'.encode())
                ret1 = p.readline()
                #print(ret1) #T:####### C:########\r\n
                ret1 = ret1.decode('UTF-8').replace('T:','').replace('C:','').replace("\r\n",'').split(' ')
                try:
                    setpoint = float(ret1[0])
                except Exception:
                    setpoint = -999.0
                readback = float(ret1[1])
                ret2 = p.readline()
            self.cached_setpoint = setpoint
            self.cached_readback = readback
            self.cached_time = time.time()
            return (setpoint,readback)
        except Exception as e:
            print(f'EXCEPTION UPDATING TEMP {e}: RETURNING FROM CACHE')
            return (self.cached_setpoint, self.cached_readback)
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
