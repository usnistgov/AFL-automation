from abc import ABC, abstractmethod
from typing import Dict
import pathlib

import pandas as pd  # type: ignore

_MIX_DB = None

class MixDB:
    def __init__(self,db_spec):
        self.db_spec = db_spec
        self.engine = _get_engine(db_spec)
        self.set_db()

    def set_db(self):
        global _MIX_DB
        _MIX_DB = self

    @staticmethod
    def get_db():
        global _PREPARE_DB
        if _PREPARE_DB is None:
            raise ValueError('No DB set! Instantiate a PrepareDB object!')
        return _PREPARE_DB

    def add_component(self, component_dict: Dict):
        self.engine.add_component(component_dict)

    def get_component(self,name=None,uid=None):
        if (name is None) == (uid is None): # XOR
            raise ValueError(
                f"Must specify either name or uid. You passed name={name}, uid={uid}"
            )
        return self.engine.get_component(name=name,uid=uid)



def _get_engine(db_spec):
    db = None
    if pathlib.Path(db_spec).suffix == 'json':
        dataframe = pd.read_json(db_spec).T
        db = Pandas_DBEngine(dataframe)
    elif pathlib.Path(db_spec).suffix == 'csv':
        dataframe = pd.read_json(db_spec).T
        db = Pandas_DBEngine(dataframe)
    elif db_spec.startswith("http"):
        raise NotImplementedError("HTTP not yet implemented")
        # db = Tiled_DBEngine(db_spec)
    else:
        raise ValueError(f'Unable to open or connect to db: {db_spec}')
    return db

class DBEngine(ABC):
    @abstractmethod
    def add_component(self, componnent_dict: Dict):
        raise NotImplementedError("Must be implemented by subclass")

    @abstractmethod
    def get_component(self,name=None,uid=None):
        raise NotImplementedError("Must be implemented by subclass")

class Pandas_DBEngine(DBEngine):
    def __init__(self,dataframe:pd.DataFrame):
        self.dataframe = dataframe

    def add_component(self, component_dict: Dict):
        self.dataframe = self.dataframe.concat(component_dict, ignore_index=True)

    def get_component(self, name=None, uid=None):
        return self.dataframe.set_index('name').loc[name].to_dict()

