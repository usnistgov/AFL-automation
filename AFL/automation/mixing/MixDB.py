import uuid
from abc import ABC, abstractmethod
from typing import Optional, Dict
import pathlib

import pandas as pd  # type: ignore

from AFL.automation.shared.exceptions import NotFoundError

# Global variable to store the last instantiated MixDB instance
_MIXDB = None

class MixDB:
    def __init__(self,db_spec: Optional[str | pathlib.Path | pd.DataFrame]=None):
        if db_spec is None:
            db_spec = pathlib.Path.home()/'.afl/component.db.json'

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

    def add_component(self, component_dict: Dict):
        if 'uid' not in component_dict:
            component_dict['uid'] = str(uuid.uuid4())
        self.engine.add_component(component_dict)

    def get_component(self,name=None,uid=None):
        if (name is None) == (uid is None): # XOR
            raise ValueError(
                f"Must specify either name or uid. You passed name={name}, uid={uid}"
            )
        return self.engine.get_component(name=name,uid=uid)




class DBEngine(ABC):
    @abstractmethod
    def add_component(self, component_dict: Dict):
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def get_component(self,name=None,uid=None):
        raise NotImplementedError("Must be implemented by subclass")

class Pandas_DBEngine(DBEngine):
    def __init__(self,dataframe:pd.DataFrame):
        self.dataframe = dataframe

    def add_component(self, component_dict: Dict) -> None:
        self.dataframe = pd.concat([self.dataframe,pd.DataFrame(component_dict,index=[0])], ignore_index=True,axis=0)

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



def _get_engine(db_spec: str | pathlib.Path | pd.DataFrame) -> DBEngine:
    if isinstance(db_spec, str):
        db_spec = pathlib.Path(db_spec)

    db = None
    if isinstance(db_spec, pd.DataFrame):
        db = Pandas_DBEngine(db_spec)
    elif db_spec.suffix == 'json':
        dataframe = pd.read_json(db_spec).T
        db = Pandas_DBEngine(dataframe)
    elif db_spec.suffix == 'csv':
        dataframe = pd.read_json(db_spec).T
        db = Pandas_DBEngine(dataframe)
    elif str(db_spec).startswith("http"):
        raise NotImplementedError("HTTP not yet implemented")
        # db = Tiled_DBEngine(db_spec)
    else:
        raise ValueError(f'Unable to open or connect to db: {db_spec}')
    return db
