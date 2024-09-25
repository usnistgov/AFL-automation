import pytest
import uuid
import json

import pandas as pd

from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared.exceptions import NotFoundError

@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "test.config.json"

@pytest.fixture
def mixdb_pconf(config_path):
    return MixDB(config_path)

def test_add_component(mixdb_pconf):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    mixdb_pconf.add_component(component)
    uid = list(mixdb_pconf.engine.config.config.keys())[0]
    assert mixdb_pconf.engine.config.config[uid]['name'] == 'H2O'
    assert mixdb_pconf.engine.config.config[uid]['density'] == '1 g/ml'

def test_get_component_by_name(mixdb_pconf):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    mixdb_pconf.add_component(component)
    retrieved_component = mixdb_pconf.get_component(name='H2O')
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '1 g/ml'

def test_update_component(mixdb_pconf):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    uid = mixdb_pconf.add_component(component)
    component = {'name': 'H2O', 'density': '0.998 g/ml', 'uid': uid}
    mixdb_pconf.add_component(component)
    retrieved_component = mixdb_pconf.get_component(name='H2O')
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '0.998 g/ml'

def test_multiple_component(mixdb_pconf):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    mixdb_pconf.add_component(component)
    component = {'name': 'H2O', 'density': '0.998 g/ml'}
    mixdb_pconf.add_component(component)
    retrieved_component = mixdb_pconf.get_component(name='H2O')
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '0.998 g/ml'

def test_get_component_by_uid(mixdb_pconf):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    mixdb_pconf.add_component(component)
    uid = list(mixdb_pconf.engine.config.config.keys())[0]
    retrieved_component = mixdb_pconf.get_component(uid=uid)
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '1 g/ml'

def test_get_component_not_found(mixdb_pconf):
    with pytest.raises(NotFoundError):
        mixdb_pconf.get_component(name='NonExistent',interactive=False)

def test_write(mixdb_pconf, config_path):
    component = {'name': 'H2O', 'density': '1 g/ml'}
    uid1 = mixdb_pconf.add_component(component)
    component = {'name': 'D2O', 'density': '1.11 g/ml'}
    uid2 = mixdb_pconf.add_component(component)
    mixdb_pconf.write()
    assert config_path.exists()

    with open(config_path,'r') as f:
        config_json = json.load(f)
    keys = mixdb_pconf.engine.config._get_sorted_history_keys()
    assert config_json[keys[-1]][uid1]['name'] == 'H2O'
    assert config_json[keys[-1]][uid1]['density'] == '1 g/ml'
    assert config_json[keys[-1]][uid2]['name'] == 'D2O'
    assert config_json[keys[-1]][uid2]['density'] == '1.11 g/ml'

def test_add_component_with_uid(mixdb_pconf):
    uid = str(uuid.uuid4())
    component = {'uid': uid, 'name': 'H2O', 'density': '1 g/ml'}
    mixdb_pconf.add_component(component)
    retrieved_component = mixdb_pconf.get_component(uid=uid)
    assert retrieved_component['uid'] == uid
    assert retrieved_component['name'] == 'H2O'
    assert retrieved_component['density'] == '1 g/ml'