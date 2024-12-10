from setuptools import setup,Extension,find_packages
import numpy as np

setup(
    name='AFL-automation',
    description='Hardware interfacing code for the Autonomous Formulation Lab',
    author='Tyler B. Martin and Peter A. Beaucage',
    author_email = 'tyler.martin@nist.gov',
    version='0.0.1',
    packages=find_packages(where='.'),
    license='LICENSE',
    long_description=open('README.md').read(),
    scripts=['launchers/roboctl'],
    entry_points={
        'tiled.special_client': [
                'afl.event_catalog = AFL.automation.APIServer.data.TiledClients.CatalogOfAFLEvents:CatalogOfAFLEvents'
                ]
    }
)
