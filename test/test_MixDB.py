import os

import pytest
import pandas as pd
from AFL.automation.mixing.MixDB import MixDB

def test_mixdb_initialization(mixdb):
    assert mixdb is not None
    assert mixdb.engine is not None

    assert MixDB.get_db() is mixdb

def test_add_component(mixdb):
    new_component = {
        'name': 'component4',
        'density': '3.0 g/ml'
    }
    mixdb.add_component(new_component)
    component = mixdb.get_component(name='component4')
    assert component['name'] == 'component4'
    assert component['density'] == '3.0 g/ml'
    assert pd.isna(component['formula'])

def test_get_component_by_name(mixdb):
    component = mixdb.get_component(name='H2O')
    assert component['name'] == 'H2O'
    assert component['density'] == '1.0 g/ml'
    assert pd.isna(component['formula'])

def test_get_component_by_uid(mixdb):
    component = mixdb.get_component(uid='e2777302-6565-4d4e-b9b4-800401db4ca2')
    assert component['name'] == 'Hexanes'
    assert component['density'] == '661 kg/m^3'
    assert component['formula'] == 'C6H14'

def test_get_component_invalid(mixdb):
    with pytest.raises(ValueError):
        mixdb.get_component()