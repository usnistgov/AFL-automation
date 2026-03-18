import json
import uuid

import pytest
from tiled.client.container import Container

from AFL.automation.APIServer.data.TiledClients.CatalogOfAFLEvents import CatalogOfAFLEvents
from AFL.automation.mixcalc.MixDB import MixDB, Tiled_DBEngine
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
    assert 'formula' not in component

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

def test_get_component_omits_empty_optional_fields(mixdb):
    component = mixdb.get_component(name='NaCl')
    assert component['name'] == 'NaCl'
    assert 'density' not in component
    assert 'formula' not in component

def test_add_component_drops_empty_optional_fields_roundtrip(mixdb):
    uid = str(uuid.uuid4())
    component = {
        'uid': uid,
        'name': 'EmptyOptional',
        'density': '',
        'formula': '   ',
        'sld': '',
    }
    mixdb.add_component(component)
    retrieved_component = mixdb.get_component(uid=uid)

    assert retrieved_component['uid'] == uid
    assert retrieved_component['name'] == 'EmptyOptional'
    assert 'density' not in retrieved_component
    assert 'formula' not in retrieved_component
    assert 'sld' not in retrieved_component

def test_list_components_omits_missing_values(mixdb):
    components = mixdb.list_components()
    h2o = next(comp for comp in components if comp['name'] == 'H2O')
    nacl = next(comp for comp in components if comp['name'] == 'NaCl')

    assert 'formula' not in h2o
    assert 'density' not in nacl
    assert 'formula' not in nacl


def test_catalog_of_afl_events_string_lookup_uses_container_getitem(monkeypatch):
    catalog = object.__new__(CatalogOfAFLEvents)

    def fake_getitem(self, key):
        assert self is catalog
        assert key == 'components'
        return 'components-container'

    monkeypatch.setattr(Container, '__getitem__', fake_getitem)

    assert catalog['components'] == 'components-container'


def test_catalog_of_afl_events_negative_index_reads_values():
    catalog = object.__new__(CatalogOfAFLEvents)
    catalog.values = lambda: ['older', 'newer']

    assert catalog[-1] == 'newer'


def test_catalog_of_afl_events_positive_index_is_unsupported():
    catalog = object.__new__(CatalogOfAFLEvents)

    with pytest.raises(TypeError, match='Positive integer indexing is not supported'):
        catalog[1]


def test_tiled_get_components_container_recovers_from_conflict():
    class FakeConflictError(Exception):
        def __init__(self):
            self.response = type('Response', (), {'status_code': 409})()

    class FakeClient:
        def __init__(self):
            self.container = object()
            self.lookup_calls = 0
            self.create_calls = 0

        def __getitem__(self, key):
            assert key == 'components'
            self.lookup_calls += 1
            if self.lookup_calls == 1:
                raise KeyError(key)
            return self.container

        def create_container(self, key, metadata):
            assert key == 'components'
            assert metadata == {'type': 'components'}
            self.create_calls += 1
            raise FakeConflictError()

    engine = object.__new__(Tiled_DBEngine)
    engine.client = FakeClient()

    container = engine._get_components_container(create=True)

    assert container is engine.client.container
    assert engine.client.lookup_calls == 2
    assert engine.client.create_calls == 1
