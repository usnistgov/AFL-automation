from setuptools import setup,Extension,find_packages
import numpy as np

setup(
    name='AFL-automation',
	ext_modules= cythonize(ext_modules),
    description='A python library for automated sample creation using the OT-2 robot',
    author='Tyler B. Martin and Peter A. Beaucage',
    author_email = 'tyler.martin@nist.gov',
    version='0.0.1',
    packages=find_packages(where='.'),
    license='LICENSE',
    long_description=open('README.md').read(),
)
