#!python
from __future__ import division,print_function
from Roboto.Component import Component
from Roboto.Mixture import Mixture
import unittest
import numpy as np

class Component_TestCase(unittest.TestCase):
    def test_create(self):
        '''Can we create a component object? '''
        density = 1.11
        volume = 0.5
        D2O = Component('D2O',density=1.11,volume=volume)
        mass = volume*density
        
        np.testing.assert_array_almost_equal(D2O.density,density)
        np.testing.assert_array_almost_equal(D2O.volume,volume)
        np.testing.assert_array_almost_equal(D2O.mass,mass)

    def test_scale(self):
        '''Can we scale a component object? '''
        density = 1.11
        volume = 0.5
        D2O = Component('D2O',density=1.11,volume=volume)
        mass = volume*density

        scale = 1.35
        D2O = D2O*scale

        
        np.testing.assert_array_almost_equal(D2O.volume,volume*scale)
        np.testing.assert_array_almost_equal(D2O.mass,mass*scale)
        np.testing.assert_array_almost_equal(D2O.density,density)
        
    def test_assign(self):
        '''Does the mass/volume update appropriately?'''
        density = 1.11
        volume = 0.5
        mass = density*volume
        D2O = Component('D2O',density=density,volume=volume,mass=mass)
        
        
        mass = 0.5
        volume = mass/density
        D2O.mass = mass
        
        np.testing.assert_array_almost_equal(D2O.density,density)
        np.testing.assert_array_almost_equal(D2O.volume,volume)
        np.testing.assert_array_almost_equal(D2O.mass,mass)
        
    def test_add_identical(self):
        '''Can we add two of the same components together?'''
        density = 1.11
        
        volume1 = 0.5
        mass1 = density*volume1
        D2O_1 = Component('D2O',density=density,volume=volume1,mass=mass1)
        
        volume2 = 0.35
        mass2 = density*volume1
        D2O_2 = Component('D2O',density=density,volume=volume2,mass=mass2)
        
        D2O_3 = D2O_1 + D2O_2
        
        np.testing.assert_array_almost_equal(D2O_3.mass,D2O_1.mass+D2O_2.mass)
        np.testing.assert_array_almost_equal(D2O_3.volume,D2O_1.volume+D2O_2.volume)
        np.testing.assert_array_almost_equal(D2O_3.density,D2O_1.density)

    def test_add_different(self):
        '''Can we add two components to create a mixture?'''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)
        
        with self.assertRaises(ValueError):
            mix = D2O + H2O
        
        # new_density = (D2O.mass + H2O.mass)/(D2O.mass/D2O.density + H2O.mass/H2O.density)
        # np.testing.assert_array_almost_equal(mix.mass,D2O.mass+H2O.mass)
        # np.testing.assert_array_almost_equal(mix.volume,D2O.volume+H2O.volume)
        # np.testing.assert_array_almost_equal(mix.density,new_density)


        
if __name__ == '__main__':
    import unittest 
    suite = unittest.TestLoader().loadTestsFromTestCase(Component_TestCase)
    unittest.TextTestRunner(verbosity=2).run(suite)
