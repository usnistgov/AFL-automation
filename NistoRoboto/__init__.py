from NistoRoboto.Component import Component
from NistoRoboto.Mixture import Mixture

def test():
    r"""
    Run all tests using pytest.
    """
    import os
    import pytest
    path = os.path.split(__file__)[0]
    pytest.main(['-x',path])
