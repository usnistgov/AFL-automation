import test_common
import unittest
import time
import sys

from qmixsdk import qmixbus
from qmixsdk import qmixpump
from qmixsdk import qmixvalve
from qmixsdk.qmixbus import UnitPrefix, TimeUnit

class CapiNemesysTestCase(test_common.QmixTestBase):
    """
    Test for testing the python integration of the QmixSDK pump interface
    """

    def step01_capi_open(self):
        print("Opening bus with deviceconfig ", deviceconfig)
        self.bus = qmixbus.Bus()
        self.bus.open(deviceconfig, 0)


    def step02_device_name_lookup(self):
        print("Looking up devices...")
        self.pump = qmixpump.Pump()
        self.pump.lookup_by_name("neMESYS_Low_Pressure_1_Pump")
        pumpcount = qmixpump.Pump.get_no_of_pumps()
        print("Number of pumps: ", pumpcount)
        for i in range (pumpcount):
            pump2 = qmixpump.Pump()
            pump2.lookup_by_device_index(i)
            print("Name of pump ", i, " is ", pump2.get_device_name())



    def step03_bus_start(self):
        print("Starting bus communication...")
        self.bus.start()


    def step04_pump_enable(self):
        print("Enabling pump drive...")
        if self.pump.is_in_fault_state():
            self.pump.clear_fault()
        self.assertFalse(self.pump.is_in_fault_state())
        if not self.pump.is_enabled():
            self.pump.enable(True)
        self.assertTrue(self.pump.is_enabled())
    

    @staticmethod
    def wait_calibration_finished(pump, timeout_seconds):
        """
        The function waits until the given pump has finished calibration or
        until the timeout occurs.
        """
        timer = qmixbus.PollingTimer(timeout_seconds * 1000)
        result = False
        while (result == False) and not timer.is_expired():
            time.sleep(0.1)
            result = pump.is_calibration_finished()
        return result


    @staticmethod
    def wait_dosage_finished(pump, timeout_seconds):
        """
        The function waits until the last dosage command has finished
        until the timeout occurs.
        """
        timer = qmixbus.PollingTimer(timeout_seconds * 1000)
        message_timer = qmixbus.PollingTimer(500)
        result = True
        while (result == True) and not timer.is_expired():
            time.sleep(0.1)
            if message_timer.is_expired():
                print("Fill level: ", pump.get_fill_level())
                message_timer.restart()
            result = pump.is_pumping()
        return not result
        

    def step06_calibration(self):
        print("Calibrating pump...")
        self.pump.calibrate()
        time.sleep(0.2)
        calibration_finished = self.wait_calibration_finished(self.pump, 30)
        print("Pump calibrated: ", calibration_finished)
        self.assertEqual(calibration_finished, True)


    def step07_syringeconfig(self):
        print("Testing syringe configuration...")
        inner_diameter_set = 1
        piston_stroke_set = 60
        self.pump.set_syringe_param(inner_diameter_set, piston_stroke_set)
        syringe = self.pump.get_syringe_param()
        self.assertEqual(inner_diameter_set, syringe.inner_diameter_mm)
        self.assertEqual(piston_stroke_set, syringe.max_piston_stroke_mm)


    def step08_si_units(self):
        print("Testing SI units...")
        self.pump.set_volume_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres)
        max_ml = self.pump.get_volume_max()
        print("Max. volume ml: ", max_ml, self.pump.get_volume_unit())
        self.pump.set_volume_unit(qmixpump.UnitPrefix.unit, qmixpump.VolumeUnit.litres)
        max_l = self.pump.get_volume_max()
        print("Max. volume l: ", max_l, self.pump.get_volume_unit())
        self.assertAlmostEqual(max_ml, max_l * 1000)

        self.pump.set_flow_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres, 
            qmixpump.TimeUnit.per_second)
        max_ml_s = self.pump.get_flow_rate_max()
        print("Max. flow ml/s: ", max_ml_s, self.pump.get_flow_unit())
        self.pump.set_flow_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres, 
            qmixpump.TimeUnit.per_minute)    
        max_ml_min = self.pump.get_flow_rate_max()
        print("Max. flow ml/min: ", max_ml_min, self.pump.get_flow_unit())
        self.assertAlmostEqual(max_ml_s * 60, max_ml_min)


    def step09_aspirate(self):
        print("Testing aspiration...")
        max_volume = self.pump.get_volume_max() / 2
        max_flow = self.pump.get_flow_rate_max()
        self.pump.aspirate(max_volume, max_flow)
        finished = self.wait_dosage_finished(self.pump, 30)
        self.assertEqual(True, finished)


    def step10_dispense(self):
        print("Testing dispensing...")
        max_volume = self.pump.get_volume_max() / 10
        max_flow = self.pump.get_flow_rate_max() / 2
        self.pump.dispense(max_volume, max_flow)
        finished = self.wait_dosage_finished(self.pump, 20)
        self.assertEqual(True, finished)


    def step11_pump_volume(self):
        print("Testing pumping volume...")
        max_volume = self.pump.get_volume_max() / 10
        max_flow = self.pump.get_flow_rate_max()

        self.pump.pump_volume(0 - max_volume, max_flow)
        finished = self.wait_dosage_finished(self.pump, 10)
        self.assertEqual(True, finished)

        self.pump.pump_volume(max_volume, max_flow)
        finished = self.wait_dosage_finished(self.pump, 10)
        self.assertEqual(True, finished)


    def step12_generate_flow(self):
        print("Testing generating flow...")
        max_flow = self.pump.get_flow_rate_max()
        self.pump.generate_flow(max_flow)
        time.sleep(1)
        flow_is = self.pump.get_flow_is()
        #self.assertAlmostEqual(max_flow, flow_is)
        finished = self.wait_dosage_finished(self.pump, 30)
        self.assertEqual(True, finished)     


    def step13_set_syringe_level(self):
        print("Testing set syringe fill level...")
        max_flow = self.pump.get_flow_rate_max() / 2
        max_volume = self.pump.get_volume_max() / 2
        self.pump.set_fill_level(max_volume, max_flow)
        finished = self.wait_dosage_finished(self.pump, 30)
        self.assertEqual(True, finished)     

        fill_level_is = self.pump.get_fill_level()
        #self.assertAlmostEqual(max_volume, fill_level_is)

        self.pump.set_fill_level(0, max_flow)
        finished = self.wait_dosage_finished(self.pump, 30)
        self.assertEqual(True, finished)  

        fill_level_is = self.pump.get_fill_level()
        self.assertAlmostEqual(0, fill_level_is)  

    def step14_valve(self):
        print("Testing valve...")
        if not self.pump.has_valve():
            print("no valve installed")
            return

        valve = self.pump.get_valve()
        valve_pos_count = valve.number_of_valve_positions()
        print("Valve positions: ", valve_pos_count)
        for i in range (valve_pos_count):
            valve.switch_valve_to_position(i)
            time.sleep(0.2) # give valve some time to move to target
            valve_pos_is = valve.actual_valve_position()
            self.assertEqual(i, valve_pos_is)
        valve.switch_valve_to_position(0)

    def step25_capi_close(self):
        print("Closing bus...")
        self.bus.stop()
        self.bus.close()


    
if __name__ == '__main__':
    deviceconfig = test_common.parse_test_args("single-pump")
    del sys.argv[1:]
    unittest.main()
