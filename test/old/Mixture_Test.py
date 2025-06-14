#!python
from __future__ import division,print_function
from AFL.automation.Mixture import Mixture
from AFL.automation.Component import Component
from AFL.automation.Exceptions import EmptyException
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
        np.testing.assert_almost_equal(mix.mass,D2O.mass+H2O.mass)
        np.testing.assert_almost_equal(mix.volume,D2O.volume+H2O.volume)
        np.testing.assert_almost_equal(mix.density,new_density)

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
        np.testing.assert_almost_equal(mix.mass  ,D2O_1.mass  +D2O_2.mass  +H2O.mass)
        np.testing.assert_almost_equal(mix.volume,D2O_1.volume+D2O_2.volume+H2O.volume)
        np.testing.assert_almost_equal(mix.density,new_density)

        # ensure the D2O component was properly combined
        np.testing.assert_array_almost_equal(mix['D2O'].mass  ,D2O_1.mass  +D2O_2.mass)
        np.testing.assert_array_almost_equal(mix['D2O'].volume,D2O_1.volume+D2O_2.volume)

    def test_add_new(self):
        '''Can we add a new component to a Mixture object? '''
        # create three components
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        density3 = 0.789
        mass3 =  0.3
        EtOH = Component('EtOH',formula='C2H5OH',density=density3,mass=mass3)

        # create base mixture then add third component
        solution = Mixture([H2O,D2O]) 
        mix = solution + EtOH

        # base sanity check
        self.assertTrue(mix.contains('D2O'))
        self.assertTrue(mix.contains('H2O'))
        self.assertTrue(mix.contains('EtOH'))


        # ensure total solution properties 
        new_density = (D2O.mass + H2O.mass + EtOH.mass)/(D2O.mass/D2O.density + H2O.mass/H2O.density + EtOH.mass/EtOH.density)
        np.testing.assert_almost_equal(mix.mass  ,D2O.mass  + H2O.mass  + EtOH.mass)
        np.testing.assert_almost_equal(mix.volume,D2O.volume + H2O.volume+EtOH.volume)
        np.testing.assert_almost_equal(mix.density,new_density)

    def test_set_volume_fraction(self):
        '''Can we set the volume fraction of the mixture?'''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        density3 = 0.789
        mass3 =  0.3
        volume3 = mass3/density3
        EtOH = Component('EtOH',formula='C2H5OH',density=density3,mass=mass3,volume=volume3)


        mix = Mixture([D2O,H2O,EtOH])

        np.testing.assert_almost_equal(mix.volume_fraction['D2O'],volume1/(volume1+volume2+volume3))
        np.testing.assert_almost_equal(mix.volume_fraction['H2O'],volume2/(volume1+volume2+volume3))
        np.testing.assert_almost_equal(mix.volume_fraction['EtOH'],volume3/(volume1+volume2+volume3))
        vfrac_set = {'D2O':0.1,'H2O':0.5,'EtOH':0.4}
        mix.set_volume_fractions(vfrac_set)

        #sanity check
        np.testing.assert_almost_equal(mix.volume_fraction['D2O'],mix.volume_fraction['D2O'])
        np.testing.assert_almost_equal(mix.volume_fraction['H2O'],mix.volume_fraction['H2O'])
        np.testing.assert_almost_equal(mix.volume_fraction['EtOH'],mix.volume_fraction['EtOH'])

        np.testing.assert_almost_equal(mix['D2O'].volume,mix.volume*vfrac_set['D2O'])
        np.testing.assert_almost_equal(mix['H2O'].volume,mix.volume*vfrac_set['H2O'])
        np.testing.assert_almost_equal(mix['EtOH'].volume,mix.volume*vfrac_set['EtOH'])

    def test_set_mass_fraction(self):
        '''Can we set the mass fraction of the mixture?'''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        density3 = 0.789
        mass3 =  0.3
        volume3 = mass3/density3
        EtOH = Component('EtOH',formula='C2H5OH',density=density3,mass=mass3,volume=volume3)

        mix = Mixture([D2O,H2O,EtOH])

        np.testing.assert_almost_equal(mix.mass_fraction['D2O'],mass1/(mass1+mass2+mass3))
        np.testing.assert_almost_equal(mix.mass_fraction['H2O'],mass2/(mass1+mass2+mass3))
        np.testing.assert_almost_equal(mix.mass_fraction['EtOH'],mass3/(mass1+mass2+mass3))
        
        mfrac_set = {'D2O':7/15,'H2O':8/30,'EtOH':4/15}
        mix.set_mass_fractions(mfrac_set)

        #sanity check
        np.testing.assert_almost_equal(mix.mass_fraction['D2O'],mix.mass_fraction['D2O'])
        np.testing.assert_almost_equal(mix.mass_fraction['H2O'],mix.mass_fraction['H2O'])
        np.testing.assert_almost_equal(mix.mass_fraction['EtOH'],mix.mass_fraction['EtOH'])

        np.testing.assert_almost_equal(mix['D2O'].mass,mix.mass*mfrac_set['D2O'])
        np.testing.assert_almost_equal(mix['H2O'].mass,mix.mass*mfrac_set['H2O'])
        np.testing.assert_almost_equal(mix['EtOH'].mass,mix.mass*mfrac_set['EtOH'])

    def test_set_mass_concentration(self):
        '''Can we set the concentration of a solute?'''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mass3 =  0.3
        polymer = Component('polymer',mass=mass3)

        mix = Mixture([D2O,H2O,polymer])
        mix.set_mass_concentration('polymer',1.25)

        np.testing.assert_almost_equal(mix.concentration['polymer'],1.25)
        np.testing.assert_almost_equal(mix['polymer'].mass,1.25*mix.volume)

    def test_set_mass_concentration_by_dilution(self):
        '''Can we set the concentration of a solute?'''
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mass3 =  0.3
        polymer = Component('polymer',mass=mass3)

        mix = Mixture([D2O,H2O,polymer])
        mix.set_mass_concentration('polymer',1.25,by_dilution=True)

        np.testing.assert_almost_equal(mix.concentration['polymer'],1.25)
        np.testing.assert_almost_equal(mix.volume,mix['polymer'].mass/1.25)

    def test_set_total_volume(self):
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)


        mass3 =  0.3
        polymer = Component('polymer',mass=mass3)

        mix = Mixture([D2O,H2O,polymer])
        pre_mass_fractions = mix.mass_fraction
        pre_volume_fractions = mix.volume_fraction

        target_volume = 1.2
        mix.volume = target_volume

        np.testing.assert_almost_equal(mix['D2O'].volume,volume1*target_volume/(volume1 + volume2))
        np.testing.assert_almost_equal(mix['H2O'].volume,volume2*target_volume/(volume1 + volume2))
        np.testing.assert_almost_equal(mix.volume,target_volume)


        np.testing.assert_almost_equal(mix.volume_fraction['H2O'],pre_volume_fractions['H2O'])
        np.testing.assert_almost_equal(mix.volume_fraction['D2O'],pre_volume_fractions['D2O'])

        # mass fractions will change because polymer volume isn't specified and therefore isn't
        # modified by the volume setter
        # np.testing.assert_almost_equal(mix.mass_fraction['H2O'],pre_mass_fractions['H2O'])
        # np.testing.assert_almost_equal(mix.mass_fraction['D2O'],pre_mass_fractions['D2O'])
        # np.testing.assert_almost_equal(mix.mass_fraction['polymer'],pre_mass_fractions['polymer'])

    def test_set_total_mass(self):
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mass3 =  0.3
        polymer = Component('polymer',mass=mass3)

        mix = Mixture([D2O,H2O,polymer])
        pre_mass_fractions = mix.mass_fraction
        pre_volume_fractions = mix.volume_fraction

        target_mass = 1.2
        mix.mass = target_mass

        np.testing.assert_almost_equal(mix.mass,target_mass)
        np.testing.assert_almost_equal(mix['H2O'].mass,mass2*target_mass/(mass1 + mass2 + mass3))
        np.testing.assert_almost_equal(mix['D2O'].mass,mass1*target_mass/(mass1 + mass2 + mass3))
        np.testing.assert_almost_equal(mix['polymer'].mass,mass3*target_mass/(mass1 + mass2 + mass3))
        np.testing.assert_almost_equal(mix.mass_fraction['H2O'],pre_mass_fractions['H2O'])
        np.testing.assert_almost_equal(mix.mass_fraction['D2O'],pre_mass_fractions['D2O'])
        np.testing.assert_almost_equal(mix.mass_fraction['polymer'],pre_mass_fractions['polymer'])

        np.testing.assert_almost_equal(mix.volume_fraction['H2O'],pre_volume_fractions['H2O'])
        np.testing.assert_almost_equal(mix.volume_fraction['D2O'],pre_volume_fractions['D2O'])

    def test_remove_volume(self):
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mass3 =  0.3
        polymer = Component('polymer',mass=mass3)

        mix1 = Mixture([D2O,H2O])

        pre_mass_fractions = mix1.mass_fraction
        pre_volume_fractions = mix1.volume_fraction
        removed_volume = 0.075
        removed = mix1.remove_volume(removed_volume)

        np.testing.assert_almost_equal(mix1.volume,volume1+volume2-removed_volume)
        np.testing.assert_almost_equal(removed.volume,removed_volume)
        np.testing.assert_almost_equal(mix1.mass_fraction['H2O'],pre_mass_fractions['H2O'])
        np.testing.assert_almost_equal(mix1.mass_fraction['D2O'],pre_mass_fractions['D2O'])
        np.testing.assert_almost_equal(mix1.volume_fraction['H2O'],pre_volume_fractions['H2O'])
        np.testing.assert_almost_equal(mix1.volume_fraction['D2O'],pre_volume_fractions['D2O'])

        # can't remove more volume than mixture contains
        with self.assertRaises(EmptyException):
            mix1.remove_volume(10)


        # can't remove volume from mixture since polymer volume isn't specified
        mix2 = Mixture([D2O,H2O,polymer])
        with self.assertRaises(RuntimeError):
            mix2.remove_volume(0.001)

    def test_remove_mass(self):
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        mass3 =  0.3
        polymer = Component('polymer',mass=mass3)

        mix = Mixture([D2O,H2O,polymer])

        pre_mass_fractions = mix.mass_fraction
        pre_volume_fractions = mix.volume_fraction

        removed_mass = 0.075
        removed = mix.remove_mass(removed_mass)

        np.testing.assert_almost_equal(mix.mass,mass1+mass2+mass3-removed_mass)
        np.testing.assert_almost_equal(removed.mass,removed_mass)
        np.testing.assert_almost_equal(mix.mass_fraction['H2O'],pre_mass_fractions['H2O'])
        np.testing.assert_almost_equal(mix.mass_fraction['D2O'],pre_mass_fractions['D2O'])
        np.testing.assert_almost_equal(mix.mass_fraction['polymer'],pre_mass_fractions['polymer'])
        np.testing.assert_almost_equal(mix.volume_fraction['H2O'],pre_volume_fractions['H2O'])
        np.testing.assert_almost_equal(mix.volume_fraction['D2O'],pre_volume_fractions['D2O'])

        # can't remove more volume than mixture contains
        with self.assertRaises(EmptyException):
            mix.remove_mass(10)

    def test_equals(self):
        '''Can we compare two mixtures?'''
        # create three components
        density1 = 1.11
        volume1 = 0.5
        mass1 = volume1*density1
        D2O = Component('D2O',density=density1,volume=volume1,mass=mass1)

        density2 = 1.00
        volume2 = 0.15
        mass2 = volume2*density2
        H2O = Component('H2O',density=density2,volume=volume2,mass=mass2)

        density3 = 0.789
        mass3 =  0.3
        EtOH = Component('EtOH',formula='C2H5OH',density=density3,mass=mass3)

        # create base mixture then add third component
        mix1 = Mixture([H2O,D2O]) 
        mix2 = mix1 + EtOH

        self.assertFalse((mix1 == mix2))
        self.assertTrue(((mix1+EtOH) == mix2))



        
        
if __name__ == '__main__':
    import unittest 
    suite = unittest.TestLoader().loadTestsFromTestCase(Mixture_TestCase)
    unittest.TextTestRunner(verbosity=2).run(suite)
