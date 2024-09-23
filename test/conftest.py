import pytest
import pandas as pd
from AFL.automation.mixing.MixDB import MixDB

@pytest.fixture
def sample_dataframe():
    data = {
        'uid': [
            'd72d1bb9-b608-4b18-89be-bdbea89b52dd',
            'e2777302-6565-4d4e-b9b4-800401db4ca2',
            '949d3fab-01d5-4107-8756-eeef44a5ed4a'
        ],
        'name': ['H2O', 'Hexanes', 'NaCl'],
        'density': ['1.0 g/ml','661 kg/m^3', None],
        'formula': [None,'C6H14', None],
    }
    return pd.DataFrame(data)

@pytest.fixture
def mixdb(sample_dataframe):
    return MixDB(sample_dataframe)
