import uuid
from abc import ABC, abstractmethod
from typing import Optional, Dict
import pathlib
import json
import os

import pandas as pd  # type: ignore
import numpy as np
import tiled.client

from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared.exceptions import NotFoundError
from AFL.automation.shared.units import units, has_units

# Global variable to store the last instantiated MixDB instance
_MIXDB = None

class MixDB:
    def __init__(self,db_spec: Optional[str | pathlib.Path | pd.DataFrame]=None):
        self.default_local_spec = _resolve_afl_home() / 'component.config.json'
        if db_spec is None:
            db_spec = self.default_local_spec

        self.db_spec = db_spec
        if db_spec == self.default_local_spec:
            self.engine = _get_default_engine_with_tiled_fallback(db_spec)
        else:
            self.engine = _get_engine(db_spec)
        self.set_db()

    def set_db(self):
        global _MIXDB
        _MIXDB = self

    @staticmethod
    def _serialize_component(component_dict: Dict) -> Dict:
        """
        Convert any pint.Quantity objects in a component dictionary to strings
        for JSON serialization compatibility.
        
        Parameters
        ----------
        component_dict : Dict
            Component dictionary that may contain Quantity objects
            
        Returns
        -------
        Dict
            Component dictionary with Quantity objects converted to strings
        """
        component_dict = MixDB._normalize_component(component_dict)
        serialized = {}
        for key, value in component_dict.items():
            if has_units(value):
                serialized[key] = str(value)
            else:
                serialized[key] = value
        return serialized

    @staticmethod
    def _is_missing_value(value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ''
        # Guard pd.isna() for scalars only; containers can return arrays.
        if isinstance(value, (dict, list, tuple, set)):
            return False
        try:
            return bool(pd.isna(value))
        except Exception:
            return False

    @staticmethod
    def _normalize_component(component_dict: Dict) -> Dict:
        normalized = {}
        for key, value in component_dict.items():
            if MixDB._is_missing_value(value):
                continue
            normalized[key] = value
        return normalized

    @staticmethod
    def get_db():
        """
        Retrieve the global _MIXDB instance.

        Raises:
            ValueError: If _MIXDB is not set.

        Returns:
            The _MIXDB instance.
        """
        global _MIXDB
        if _MIXDB is None:
            raise ValueError('No DB set! Instantiate a MixDB object!')
        return _MIXDB

    def add_component(self, component_dict: Dict) -> str:
        if 'uid' not in component_dict:
            component_dict['uid'] = str(uuid.uuid4())
        # Serialize Quantity objects to strings before storing
        serialized_dict = self._serialize_component(component_dict)
        self.engine.add_component(serialized_dict)
        return serialized_dict['uid']

    def remove_component(self, name=None, uid=None):
        self.engine.remove_component(name=name, uid=uid)

    def list_components(self):
        components = self.engine.list_components()
        # Serialize any Quantity objects that might exist in the returned data
        return [self._serialize_component(self._normalize_component(comp)) for comp in components]

    def update_component(self, component_dict: Dict) -> str:
        if 'uid' not in component_dict:
            raise ValueError('uid required for update')
        # Serialize Quantity objects to strings before storing
        serialized_dict = self._serialize_component(component_dict)
        self.engine.update_component(serialized_dict)
        return serialized_dict['uid']

    def get_component(self,name=None,uid=None,interactive=False):
        if (name is None) == (uid is None): # XOR
            raise ValueError(
                f"Must specify either name or uid. You passed name={name}, uid={uid}"
            )
        try:
            component = self.engine.get_component(name=name,uid=uid)
            component = self._serialize_component(self._normalize_component(component))
        except NotFoundError:
            if interactive:
                component = self.add_component_interactive(name=name,uid=uid)
            else:
                raise
        return component

    def add_component_interactive(self, name,uid=None):
        resp = input(f'==> Attempting to add {name} to ComponentDB, continue? [yes]:')
        if resp.lower() in ['n', 'no', 'nope']:
            raise ValueError('Interactive add failed...') from None

        if uid is None:
            uid = str(uuid.uuid4())

        #description = input('--> Description of Component?:').strip()

        formula = input('--> Empirical formula? [None]:').strip()
        if not formula:
            formula = None

        density = input('--> Density? [None]:').strip().lower()
        if not density:
            density = None

        sld = input('--> SLD? [None]:').strip().lower()
        if not sld:
            sld = None
        else:
            sld = float(resp) * 10e-6 * units('angstrom^(-2)')

        resp = input('~~> Save updated db? [yes]:').strip().lower()
        if not resp:
            write = True
        elif resp in ['yes', 'y']:
            write = True
        else:
            write = False

        component_dict = dict(
             uid=uid,
             name=name,
             formula=formula,
             density=density,
             sld=sld,
        )
        self.add_component(component_dict)
        if write:
            self.write()
        return component_dict

    def write(self):
        self.engine.write(self.db_spec)

    def get_source(self) -> str:
        if hasattr(self.engine, 'source'):
            return str(self.engine.source)
        return 'local'


class DBEngine(ABC):
    @abstractmethod
    def add_component(self, component_dict: Dict) -> str:
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def update_component(self, component_dict: Dict) -> str:
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def remove_component(self,name=None,uid=None):
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def list_components(self):
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def get_component(self,name=None,uid=None):
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def write(self,filename,writer='json'):
        raise NotImplementedError("Must be implemented by subclass")

class Pandas_DBEngine(DBEngine):
    def __init__(self,dataframe:pd.DataFrame):
        self.dataframe = dataframe

    @staticmethod
    def read_csv(db_spec):
        dataframe = pd.read_csv(db_spec,sep=',').T
        return Pandas_DBEngine(dataframe)

    @staticmethod
    def read_json(db_spec):
        dataframe = pd.read_json(db_spec).T
        return Pandas_DBEngine(dataframe)

    def write(self, filename: str, writer: str = 'json') -> None:
        if writer == 'json':
            self.dataframe.T.to_json(filename)
        elif writer == 'csv':
            self.dataframe.T.to_csv(filename)
        else:
            raise ValueError(f"Invalid writer: {writer}")

    def add_component(self, component_dict: Dict) -> str:
        component_dict['uid'] = component_dict.get('uid', str(uuid.uuid4()))
        self.dataframe = pd.concat([self.dataframe,pd.DataFrame(component_dict,index=[0])], ignore_index=True,axis=0)
        return component_dict['uid']

    def update_component(self, component_dict: Dict) -> str:
        uid = component_dict['uid']
        if uid not in self.dataframe['uid'].values:
            raise NotFoundError(f"Component not found: uid={uid}")
        idx = self.dataframe.index[self.dataframe['uid'] == uid]
        for key, val in component_dict.items():
            self.dataframe.loc[idx, key] = val
        return uid

    def remove_component(self,name=None,uid=None):
        if (name is None) == (uid is None):
            raise ValueError("Must specify either name or uid")
        if uid is not None:
            self.dataframe = self.dataframe[self.dataframe['uid'] != uid]
        else:
            self.dataframe = self.dataframe[self.dataframe['name'] != name]

    def list_components(self):
        return self.dataframe.fillna('').to_dict('records')

    def get_component(self, name=None, uid=None) -> Dict:
        try:
            if name is not None:
                component_dict = self.dataframe.set_index('name').loc[name].to_dict()
                component_dict['name'] = name
            else:
                component_dict = self.dataframe.set_index('uid').loc[uid].to_dict()
                component_dict['uid'] = uid
        except KeyError:
            raise NotFoundError(f"Component not found: name={name}, uid={uid}")
        return component_dict


class PersistentConfig_DBEngine(DBEngine):
    def __init__(self, config_path: str):
        self.config = PersistentConfig(config_path)

    def add_component(self, component_dict: Dict) -> str:
        uid = component_dict.get('uid', str(uuid.uuid4()))
        self.config[uid] = component_dict
        return uid

    def update_component(self, component_dict: Dict) -> str:
        uid = component_dict['uid']
        if uid not in self.config.config:
            raise NotFoundError(f"Component not found: uid={uid}")
        self.config[uid] = component_dict
        return uid

    def remove_component(self,name=None,uid=None):
        if (name is None) == (uid is None):
            raise ValueError("Must specify either name or uid")
        if uid is not None:
            del self.config[uid]
        else:
            keys = [k for k,v in self.config.config.items() if v['name']==name]
            if not keys:
                raise NotFoundError(f"Component not found: name={name}")
            del self.config[keys[-1]]

    def list_components(self):
        return list(self.config.config.values())

    def get_component(self, name=None, uid=None) -> Dict:
        if (name is None) == (uid is None):  # XOR
            raise ValueError("Must specify either name or uid.")

        if uid is not None:
            component_dict = self.config[uid]
        else:
            all_components = self.config.config.values()
            component_list = [comp for comp in all_components if comp['name'] == name]
            if not(component_list):
                raise NotFoundError(f"Component not found: name={name}, uid={uid}")
            component_dict = component_list[-1]

        return component_dict

    def write(self, filename: str, writer: str = 'json') -> None:
        self.config.flush()


class Tiled_DBEngine(DBEngine):
    def __init__(self, server: str, api_key: str = '', fallback_engine: Optional[DBEngine] = None):
        self.server = server
        self.api_key = api_key
        self.fallback_engine = fallback_engine
        self.source = 'tiled'
        self._components_cache = None
        self._components_cache_by_uid = {}
        self._components_cache_by_name = {}
        self._components_cache_source = 'unknown'
        try:
            self.client = tiled.client.from_uri(
                server,
                api_key=api_key,
                structure_clients="dask",
            )
        except Exception:
            self.client = None
            self.source = 'local'

    @staticmethod
    def _entry_key(uid: str) -> str:
        return f'components/{uid}'

    @staticmethod
    def _extract_payload(metadata: Dict) -> Optional[Dict]:
        if not isinstance(metadata, dict):
            return None
        if isinstance(metadata.get('component'), dict):
            return dict(metadata['component'])
        if metadata.get('type') == 'component':
            out = dict(metadata)
            out.pop('type', None)
            return out
        return None

    @staticmethod
    def _fetch_item_metadata(item) -> Optional[Dict]:
        # Fast path: metadata already present on the client object.
        try:
            metadata = getattr(item, 'metadata', None)
            if isinstance(metadata, dict) and metadata:
                return metadata
        except Exception:
            pass

        # Fallback: explicitly request metadata fields from the item's self link.
        try:
            item_doc = getattr(item, 'item', None)
            if not isinstance(item_doc, dict):
                return None
            links = item_doc.get('links', {})
            if not isinstance(links, dict):
                return None
            self_link = links.get('self')
            if not self_link:
                return None
            resp = item.context.http_client.get(
                self_link,
                params={
                    'fields': ['metadata'],
                },
            )
            if not resp.is_success:
                return None
            payload = resp.json()
            data = payload.get('data', {}) if isinstance(payload, dict) else {}
            attrs = data.get('attributes', {}) if isinstance(data, dict) else {}
            metadata = attrs.get('metadata')
            if isinstance(metadata, dict):
                return metadata
        except Exception:
            pass
        return None

    def _iter_tiled_components(self):
        if self.client is None:
            return []
        out = []
        try:
            components_container = self._get_components_container(create=False)
        except Exception:
            return []
        if components_container is None:
            return []
        try:
            keys = list(components_container.keys())
        except Exception:
            return []
        for key in keys:
            try:
                item = components_container[str(key)]
                metadata = self._fetch_item_metadata(item)
                payload = self._extract_payload(metadata)
                if not payload or 'uid' not in payload:
                    continue
                out.append(payload)
            except Exception:
                continue
        return out

    def _get_components_container(self, create: bool = False):
        if self.client is None:
            return None
        try:
            return self.client['components']
        except Exception:
            if not create:
                return None
        # Container is missing. Create it at root so component entries live under components/*.
        self.client.create_container(key='components', metadata={'type': 'components'})
        return self.client['components']

    def _write_component(self, component_dict: Dict):
        if self.client is None:
            raise RuntimeError('No tiled client available.')
        uid = str(component_dict['uid'])
        components_container = self._get_components_container(create=True)
        if components_container is None:
            raise RuntimeError('Unable to access or create tiled components container.')
        self._delete_component_uid(uid)
        metadata = {
            'type': 'component',
            'uid': uid,
            'name': component_dict.get('name', ''),
            'component': component_dict,
        }
        components_container.write_array(np.array([1], dtype=np.int8), key=uid, metadata=metadata)

    def _delete_component_uid(self, uid: str) -> bool:
        components_container = self._get_components_container(create=False)
        if components_container is None:
            return False
        uid = str(uid)
        deleted = False
        try:
            del components_container[uid]
            deleted = True
        except Exception:
            pass
        if not deleted:
            try:
                obj = components_container[uid]
                if hasattr(obj, 'delete'):
                    obj.delete()
                    deleted = True
            except Exception:
                pass
        return deleted

    def _delete_key(self, key: str) -> bool:
        if self.client is None:
            return False
        deleted = False
        try:
            del self.client[key]
            deleted = True
        except Exception:
            pass
        if not deleted:
            try:
                obj = self.client[key]
                if hasattr(obj, 'delete'):
                    obj.delete()
                    deleted = True
            except Exception:
                pass
        return deleted

    def _list_components_with_source(self):
        # Only fall back to local when we cannot connect to tiled at all.
        if self.client is None and self.fallback_engine is not None:
            self.source = 'local'
            return self.fallback_engine.list_components(), 'local'
        tiled_components = self._iter_tiled_components()
        self.source = 'tiled'
        return tiled_components, 'tiled'

    def _invalidate_component_cache(self):
        self._components_cache = None
        self._components_cache_by_uid = {}
        self._components_cache_by_name = {}
        self._components_cache_source = 'unknown'

    def _populate_component_cache(self):
        components, source = self._list_components_with_source()
        self._components_cache = list(components)
        by_uid = {}
        by_name = {}
        for comp in self._components_cache:
            if not isinstance(comp, dict):
                continue
            uid = comp.get('uid')
            name = comp.get('name')
            if uid:
                by_uid[str(uid)] = comp
            if name:
                by_name.setdefault(str(name), []).append(comp)
        self._components_cache_by_uid = by_uid
        self._components_cache_by_name = by_name
        self._components_cache_source = source

    def _ensure_component_cache(self):
        if self._components_cache is None:
            self._populate_component_cache()
        self.source = self._components_cache_source

    def add_component(self, component_dict: Dict) -> str:
        uid = component_dict.get('uid', str(uuid.uuid4()))
        component_dict = dict(component_dict)
        component_dict['uid'] = uid
        try:
            self._write_component(component_dict)
            self.source = 'tiled'
            self._invalidate_component_cache()
            return uid
        except Exception:
            if self.client is None and self.fallback_engine is not None:
                self.source = 'local'
                out_uid = self.fallback_engine.add_component(component_dict)
                self._invalidate_component_cache()
                return out_uid
            raise

    def update_component(self, component_dict: Dict) -> str:
        uid = component_dict['uid']
        try:
            self._write_component(component_dict)
            self.source = 'tiled'
            self._invalidate_component_cache()
            return uid
        except Exception:
            if self.client is None and self.fallback_engine is not None:
                self.source = 'local'
                out_uid = self.fallback_engine.update_component(component_dict)
                self._invalidate_component_cache()
                return out_uid
            raise

    def remove_component(self,name=None,uid=None):
        if (name is None) == (uid is None):
            raise ValueError("Must specify either name or uid")
        if uid is None:
            component = self.get_component(name=name)
            uid = component['uid']
        deleted = self._delete_component_uid(str(uid))
        if deleted:
            self.source = 'tiled'
            self._invalidate_component_cache()
            return
        if self.client is None and self.fallback_engine is not None:
            self.source = 'local'
            self.fallback_engine.remove_component(name=name, uid=uid)
            self._invalidate_component_cache()
            return
        raise NotFoundError(f"Component not found: name={name}, uid={uid}")

    def list_components(self):
        self._ensure_component_cache()
        return list(self._components_cache)

    def get_component(self, name=None, uid=None) -> Dict:
        if (name is None) == (uid is None):  # XOR
            raise ValueError("Must specify either name or uid.")
        self._ensure_component_cache()
        if uid is not None:
            comp = self._components_cache_by_uid.get(str(uid))
            if comp:
                return comp
        else:
            matches = self._components_cache_by_name.get(str(name), [])
            if matches:
                return matches[-1]
        raise NotFoundError(f"Component not found: name={name}, uid={uid}")

    def write(self, filename: str, writer: str = 'json') -> None:
        if self.source == 'local' and self.fallback_engine is not None:
            self.fallback_engine.write(filename, writer=writer)

def _resolve_afl_home() -> pathlib.Path:
    home = os.environ.get('AFL_HOME', '')
    if home.strip():
        return pathlib.Path(home).expanduser()
    return pathlib.Path.home() / '.afl'


def _read_global_tiled_config() -> tuple[str, str]:
    config_path = _resolve_afl_home() / 'config.json'
    if not config_path.exists():
        return '', ''
    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
    except Exception:
        return '', ''
    if not isinstance(config_data, dict) or not config_data:
        return '', ''
    for key in sorted(config_data.keys(), reverse=True):
        entry = config_data.get(key, {})
        if not isinstance(entry, dict):
            continue
        server = str(entry.get('tiled_server', '')).strip()
        api_key = str(entry.get('tiled_api_key', '')).strip()
        if server:
            return server, api_key
    return '', ''


def _get_default_engine_with_tiled_fallback(default_local_spec: pathlib.Path) -> DBEngine:
    local_engine = PersistentConfig_DBEngine(str(default_local_spec))
    server, api_key = _read_global_tiled_config()
    if not server:
        return local_engine
    return Tiled_DBEngine(server=server, api_key=api_key, fallback_engine=local_engine)


def _get_engine(db_spec: str | pathlib.Path | pd.DataFrame) -> DBEngine:
    if isinstance(db_spec, str):
        if db_spec.startswith("http"):
            server = db_spec
            _, api_key = _read_global_tiled_config()
            return Tiled_DBEngine(server=server, api_key=api_key, fallback_engine=None)
        db_spec = pathlib.Path(db_spec)

    db = None
    if isinstance(db_spec, pd.DataFrame):
        db = Pandas_DBEngine(db_spec)
    elif '.config.json' in str(db_spec):
        db = PersistentConfig_DBEngine(str(db_spec))
    elif db_spec.suffix == 'json':
        db = Pandas_DBEngine.read_json(db_spec)
    elif db_spec.suffix == 'csv':
        db = Pandas_DBEngine.read_csv(db_spec)
    elif str(db_spec).startswith("http"):
        _, api_key = _read_global_tiled_config()
        db = Tiled_DBEngine(server=str(db_spec), api_key=api_key, fallback_engine=None)
    else:
        raise ValueError(f'Unable to open or connect to db: {db_spec}')
    return db
