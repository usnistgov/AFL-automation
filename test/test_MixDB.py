import os
import json
import uuid

import pytest
import pandas as pd
from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.shared.exceptions import NotFoundError


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

def test_update_component(mixdb):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    uid = mixdb.add_component(component)
    component = {'name': 'H2O', 'density': '0.998 g/ml', 'uid': uid}
    mixdb.add_component(component)
    retrieved_component = mixdb.get_component(name='H2O')
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '0.998 g/ml'

def test_multiple_component(mixdb):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    mixdb.add_component(component)
    component = {'name': 'H2O', 'density': '0.998 g/ml'}
    mixdb.add_component(component)
    retrieved_component = mixdb.get_component(name='H2O')
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '0.998 g/ml'

def test_get_component_not_found(mixdb):
    with pytest.raises(NotFoundError):
        mixdb.get_component(name='NonExistent', interactive=False)

def test_write(mixdb, component_config_path):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    uid1 = mixdb.add_component(component)
    component = {'name': 'D2O', 'density': '1.11 g/ml'}
    uid2 = mixdb.add_component(component)
    mixdb.write()
    assert component_config_path.exists()

    with open(component_config_path, 'r') as f:
        config_json = json.load(f)
    keys = mixdb.engine.config._get_sorted_history_keys()
    assert config_json[keys[-1]][uid1]['name'] == 'H2O'
    assert config_json[keys[-1]][uid1]['density'] == '1 g/ml'
    assert config_json[keys[-1]][uid2]['name'] == 'D2O'
    assert config_json[keys[-1]][uid2]['density'] == '1.11 g/ml'

def test_add_component_with_uid(mixdb):
    uid = str(uuid.uuid4())
    component = {'uid': uid, 'name': 'H2O', 'density': '1 g/ml'}
    mixdb.add_component(component)
    retrieved_component = mixdb.get_component(uid=uid)
    assert retrieved_component['uid'] == uid
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '1 g/ml'
