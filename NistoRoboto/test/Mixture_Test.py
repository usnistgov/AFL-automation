#!python
from __future__ import division,print_function
from Roboto.Mixture import Mixture
from Roboto.Component import Component
import unittest
import numpy as np

class Mixture_TestCase(unittest.TestCase):
    def test_create(self):
        '''Can we create a Mixture object? '''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mix = Mixture([H2O,D2O])

        new_density = (D2O.mass + H2O.mass)/(D2O.mass/D2O.density + H2O.mass/H2O.density)
        np.testing.assert_array_almost_equal(mix.mass,D2O.mass+H2O.mass)
        np.testing.assert_array_almost_equal(mix.volume,D2O.volume+H2O.volume)
        np.testing.assert_array_almost_equal(mix.density,new_density)

    def test_add(self):
        '''Can we add more of a component to a Mixture object? '''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O_1 = Component('D2O',density=density1,volume=volume1,mass=mass1)
        D2O_2 = (D2O_1*1.35)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mix = (Mixture([H2O,D2O_1]) + D2O_2)


        new_density = (D2O_1.mass + D2O_2.mass + H2O.mass)/(D2O_1.mass/D2O_1.density + D2O_2.mass/D2O_2.density + H2O.mass/H2O.density)
        np.testing.assert_array_almost_equal(mix.mass  ,D2O_1.mass  +D2O_2.mass  +H2O.mass)
        np.testing.assert_array_almost_equal(mix.volume,D2O_1.volume+D2O_2.volume+H2O.volume)
        np.testing.assert_array_almost_equal(mix.density,new_density)

    def test_add_new(self):
        '''Can we add more a new component to a Mixture object? '''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        density3 = 1.00
        mass3 =  0.3
        polymer = Component('polymer',density=density3,mass=mass3)

        solution = Mixture([H2O,D2O]) 
        mix = solution + polymer


        np.testing.assert_array_almost_equal(mix.mass  ,D2O.mass  +polymer.mass  +H2O.mass)
        
        
        
if __name__ == '__main__':
    import unittest 
    suite = unittest.TestLoader().loadTestsFromTestCase(Mixture_TestCase)
    unittest.TextTestRunner(verbosity=2).run(suite)
