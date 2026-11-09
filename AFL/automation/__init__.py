from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("AFL-automation")
except PackageNotFoundError:
    # Builds include this file, so version lookup never needs Git at runtime.
    try:
        from ._version import __version__
    except ImportError:
        __version__ = "could_not_determine"


def test():
    r"""
    Run all tests using pytest.
    """
    import os
    import pytest
    path = os.path.split(__file__)[0]
    pytest.main(['-x',path])
