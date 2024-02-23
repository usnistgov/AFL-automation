import serial
from AFL.automation.loading.PressureController import PressureController

class UltimusVPressureController(PressureController):
    def __init__(self,port,baud=115200):
        '''
            Initializes a DigitalOutPressureController

            Params:

                port (str): serial port to use 
        '''
        self.port = port
        self.baud = baud
        self.dispensing = False

    def compute_checksum(self,cmd):
        running_sum = 65536
        for char in cmd:
            running_sum = running_sum - char
        return hex(running_sum)[-2:].upper().encode('UTF-8')

    def char_count(self,cmd):
        return str(len(cmd)).zfill(2).encode('UTF-8')

    def package_cmd(self,cmd):
        if type(cmd)!=bytes:
            cmd.encode('UTF-8')
        cmd = self.char_count(cmd) + cmd
        cmd = cmd + self.compute_checksum(cmd)
        cmd = chr(0x02).encode('UTF-8') + cmd + chr(0x03).encode('UTF-8')
        return cmd
    def send_command(self,cmd):
        with serial.Serial(self.port,self.baud, timeout=0.5) as ser:
            print('hello')
            ser.write(chr(0x05).encode('UTF-8'))
            print(ser.read())
            print(self.package_cmd(cmd))
            ser.write(self.package_cmd(cmd))
            response = ser.read_until('\x03'.encode('UTF-8')) #ser.readline()   # read a '\n' terminated line
            core_response = response.decode('UTF-8')[2:4]
            if core_response == '2A':
                return True
            else:
                return False

            return response
    def set_P(self,pressure):
        '''
               pressure: pressure to set in psi
        '''
        if self.dispensing and pressure < 0.1:
             r = self.send_command(b'DI  ')
             if r:
                 self.dispensing = False
        if pressure > 0.1:
            p_set_str = str(int(round(pressure * 10))).zfill(4).encode('UTF-8')
        
            r = self.send_command(b'PS  ' + p_set_str)
            if not r:
                raise ValueError('Pressure set failed')
            if not self.dispensing:
                r = self.send_command(b'DI  ')
                if r:
                    self.dispensing = True 
