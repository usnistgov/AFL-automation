import uuid
from abc import ABC, abstractmethod
from typing import Optional, Dict
import pathlib
from xml.dom import NotFoundErr

import pandas as pd  # type: ignore

from AFL.automation.shared.PersistentConfig import PersistentConfig
from AFL.automation.shared.exceptions import NotFoundError
from AFL.automation.shared.units import units

# Global variable to store the last instantiated MixDB instance
_MIXDB = None

class MixDB:
    def __init__(self,db_spec: Optional[str | pathlib.Path | pd.DataFrame]=None):
        if db_spec is None:
            db_spec = pathlib.Path.home()/'.afl/component.config.json'

        self.db_spec = db_spec
        self.engine = _get_engine(db_spec)
        self.set_db()

    def set_db(self):
        global _MIXDB
        _MIXDB = self

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
        self.engine.add_component(component_dict)
        return component_dict['uid']

    def remove_component(self, name=None, uid=None):
        self.engine.remove_component(name=name, uid=uid)

    def list_components(self):
        return self.engine.list_components()

    def get_component(self,name=None,uid=None,interactive=True):
        if (name is None) == (uid is None): # XOR
            raise ValueError(
                f"Must specify either name or uid. You passed name={name}, uid={uid}"
            )
        try:
            component = self.engine.get_component(name=name,uid=uid)
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


class DBEngine(ABC):
    @abstractmethod
    def add_component(self, component_dict: Dict) -> str:
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
        self.config._update_history()

def _get_engine(db_spec: str | pathlib.Path | pd.DataFrame) -> DBEngine:
    if isinstance(db_spec, str):
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
        raise NotImplementedError("HTTP not yet implemented")
        # db = Tiled_DBEngine(db_spec)
    else:
        raise ValueError(f'Unable to open or connect to db: {db_spec}')
    return db
