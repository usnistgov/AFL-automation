# test_component.py
import pytest
from AFL.automation.mixing.Component import Component
from AFL.automation.shared.units import units

def test_component_initialization():
    component = Component(name='Water', mass='10 g', volume='10 ml', density='1 g/ml', formula='H2O')
    assert component.name == 'Water'
    assert component.mass == 10 * units.g
    assert component.volume == 10 * units.ml
    assert component.density == 1 * units.g / units.ml
    assert str(component.formula) == 'H2O'

def test_mass_setter():
    component = Component(name='Water')
    component.mass = '20 g'
    assert component.mass == 20 * units.g

def test_volume_setter():
    component = Component(name='Water', density='1 g/ml')
    component.volume = '20 ml'
    assert component.volume == 20 * units.ml
    assert component.mass == 20 * units.g

def test_density_setter():
    component = Component(name='Water')
    component.density = 1 * units.g / units.ml
    assert component.density == 1 * units.g / units.ml

def test_formula_setter():
    component = Component(name='Water')
    component.formula = 'H2O'
    assert str(component.formula) == 'H2O'

def test_add_components():
    component1 = Component(name='Water', mass='10 g', density='1 g/ml')
    component2 = Component(name='Water', mass='20 g', density='1 g/ml')
    component3 = component1 + component2
    assert component3.mass == 30 * units.g
    assert component3.density == 1 * units.g / units.ml

def test_add_components_different_names():
    component1 = Component(name='Water', mass='10 g', density='1 g/ml')
    component2 = Component(name='Ethanol', mass='20 g', density='1 g/ml')
    with pytest.raises(ValueError):
        component1 + component2

def test_add_components_different_densities():
    component1 = Component(name='Water', mass='10 g', density='1 g/ml')
    component2 = Component(name='Water', mass='20 g', density='0.8 g/ml')
    with pytest.raises(ValueError):
        component1 + component2