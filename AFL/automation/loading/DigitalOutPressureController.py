from AFL.automation.loading.PressureController import PressureController

class DigitalOutPressureController(PressureController):
    def __init__(self,digital_out,pressure_to_v_conv):
        '''
            Initializes a DigitalOutPressureController

            Params:

                digital_out (AFL.automation.DigitalOut): 
                pressure_to_v_conv (float): pressure units per volt
        '''
        self.digital_out = digital_out
        self.pressure_to_v_conv = pressure_to_v_conv

    def set_P(self,pressure):
        port = getattr(self.digital_out, 'port_to_write', 'unspecified')
        try:
            voltage = pressure / self.pressure_to_v_conv
            self._log(
                'debug',
                f'Pressure output: requested_pressure={pressure}, '
                f'conversion={self.pressure_to_v_conv} pressure units/V, '
                f'commanded_voltage={voltage:g} V, port={port}; waiting for output write.',
            )
            self.digital_out.write(voltage)
            self._log('debug', f'Pressure output write completed: port={port}, commanded_voltage={voltage:g} V.')
        except Exception as exc:
            self._log(
                'error',
                f'Pressure output failed: requested_pressure={pressure}, '
                f'conversion={self.pressure_to_v_conv} pressure units/V, port={port}: '
                f'{type(exc).__name__}: {exc}',
            )
            raise

