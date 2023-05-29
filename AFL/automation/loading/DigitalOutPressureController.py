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
        self.digital_out.write(pressure / self.pressure_to_v_conv)

