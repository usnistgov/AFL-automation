import pytest
import datetime
import pandas as pd
from AFL.automation.mixing.MixDB import MixDB
import json

@pytest.fixture
def sample_dataframe():
    data = {
        'uid': [
            'd72d1bb9-b608-4b18-89be-bdbea89b52dd',
            'e2777302-6565-4d4e-b9b4-800401db4ca2',
            '949d3fab-01d5-4107-8756-eeef44a5ed4a',
            'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        ],
        'name': ['H2O', 'Hexanes', 'NaCl', 'Mystery_Solvent'],
        'density': ['1.0 g/ml','661 kg/m^3', None, '0.9 g/ml'],
        'formula': [None,'C6H14', None, None],
    }
    return pd.DataFrame(data)

@pytest.fixture
def mixdb_df(sample_dataframe):
    return MixDB(sample_dataframe)

@pytest.fixture
def component_config_path(tmp_path):
    return tmp_path / "component.config.json"

@pytest.fixture
def mixdb(component_config_path, sample_dataframe):
    datetime_key_format = '%y/%d/%m %H:%M:%S.%f'
    key =  datetime.datetime.now().strftime(datetime_key_format)
    json_dict = {key: sample_dataframe.set_index('uid').T.to_dict('dict')}
    with open(component_config_path, 'w') as f:
        json.dump(json_dict,f)
    return MixDB(component_config_path)
