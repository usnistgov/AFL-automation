'''
helpful imports, object setup, etc. for working with AFL-automation from a Jupyter notebook or other interactive environment.
'''

import sys
import numpy as np 
import ipywidgets
import matplotlib.pyplot as plt
import requests
import datetime
import time
import json
import copy
import random
import warnings
import xarray as xr
import pandas as pd

import AFL.automation
import AFL.automation.prepare
from AFL.automation import prepare
from AFL.automation.APIServer.Client import Client
from AFL.automation.prepare.OT2Client import OT2Client
from AFL.automation.shared.utilities import tprint
from AFL.automation.shared.exceptions import MixingException
from AFL.automation.shared.units import units
from collections import defaultdict
from itertools import cycle

# some handy functions to use along widgets
from IPython.display import display, Markdown, clear_output
# widget packages
import ipywidgets as widgets
import functools


import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--noclients',action='store_true')
parser.add_argument('--noui',action='store_true')
args = parser.parse_args()
    
if not args.noclients:
    try:
        prep = OT2Client(ip='piot2',interactive=True)
        prep.login('RobotoStation')
        prep.debug(False)
    except requests.ConnectionError as e:
        warnings.warn('Failed to connect to OT2 server.')
    
    
    try:
        sample = Client(ip='localhost',port='5000',interactive=True)
        sample.login('RobotoStation')
        sample.debug(False)
    except requests.ConnectionError as e:
        warnings.warn('Failed to connect to sample server.')
    
    sample_client = sample
    

class NRUI:
    def homerobot(caller):
        prep.home()
    def refilltips(caller):
        prep.reset_tipracks()
    def transfer(caller):
        prep.transfer(NRUI.widgets['src'].value,NRUI.widgets['dest'].value,NRUI.widgets['vol'].value)
    def stop_shaker(caller):
        prep.enqueue(task_name='stop_shake')
    def unlatch_shaker(caller):
        prep.enqueue(task_name='unlatch_shaker')
    def latch_shaker(caller):
        prep.enqueue(task_name='latch_shaker')
    def set_shaker_rpm(caller):
        prep.enqueue(task_name='set_shake',rpm=NRUI.widgets['shaker_rpm'].value)
        
NRUI.tabs = {}
NRUI.tabs['robot'] = []
NRUI.tabs['shaker'] = []

NRUI.widgets = {}
NRUI.widgets['home'] = widgets.Button(description='Home')
NRUI.widgets['home'].on_click(NRUI.homerobot)
NRUI.tabs['robot'].append(NRUI.widgets['home'])

NRUI.widgets['refill'] = widgets.Button(description='Refill Tipracks')
NRUI.widgets['refill'].on_click(NRUI.refilltips)
NRUI.tabs['robot'].append(NRUI.widgets['refill'])

NRUI.widgets['src'] = widgets.Text(
    value='1A1',
    description='Source:',
    disabled=False
)
NRUI.widgets['dest'] = widgets.Text(
    value='1A1',
    description='Destination:',
    disabled=False
)
NRUI.widgets['vol'] = widgets.FloatText(
    value='0.0',
    description='Volume (uL):',
    disabled=False
)
NRUI.widgets['xfer'] = widgets.Button(description='Transfer')
NRUI.widgets['xfer'].on_click(NRUI.transfer)#functools.partial(dummyfunc,task_name='test')) #prep.transfer)
NRUI.tabs['robot'].append(widgets.VBox([NRUI.widgets['src'],NRUI.widgets['dest'],NRUI.widgets['vol'],NRUI.widgets['xfer']]))

NRUI.widgets['stop_shaker'] = widgets.Button(description='Stop Shaker')
NRUI.widgets['stop_shaker'].on_click(NRUI.stop_shaker)
NRUI.tabs['shaker'].append(NRUI.widgets['stop_shaker'])

NRUI.widgets['unlatch_shaker'] = widgets.Button(description='Unlatch Shaker')
NRUI.widgets['unlatch_shaker'].on_click(NRUI.unlatch_shaker)
NRUI.tabs['shaker'].append(NRUI.widgets['unlatch_shaker'])

NRUI.widgets['latch_shaker'] = widgets.Button(description='Latch Shaker')
NRUI.widgets['latch_shaker'].on_click(NRUI.latch_shaker)
NRUI.tabs['shaker'].append(NRUI.widgets['latch_shaker'])

NRUI.widgets['shaker_rpm'] = widgets.IntText(description='RPM',value=600)
NRUI.widgets['set_shaker_rpm'] = widgets.Button(description='Set RPM')
NRUI.widgets['set_shaker_rpm'].on_click(NRUI.set_shaker_rpm)
NRUI.tabs['shaker'].append(widgets.VBox([NRUI.widgets['shaker_rpm'],NRUI.widgets['set_shaker_rpm']]))


NRUI.robot = widgets.HBox(NRUI.tabs['robot'])
NRUI.shaker = widgets.HBox(NRUI.tabs['shaker'])

NRUI.tab = widgets.Tab()
# setting the tab windows 
NRUI.tab.children = [NRUI.robot,NRUI.shaker]
# changing the title of the first and second window
NRUI.tab.set_title(0, 'Robot')
NRUI.tab.set_title(1, 'Shaker')
  
    
print('''

Welcome to the AFL's notebook interface!!

--> Server clients are set up in interactive mode and named prep, inst, load, and sample.

--> Component, Mixture, Deck, Client, OT2Client, make_locs, units, types, PipetteAction are imported from NR.

--> Normal scientific python tools are imported (np, plt, etc.).

--> AFL utility functions such as measureEmptyTransmission and calibrateLoadertoCell are created.

--> Finally, if you are connected to the system, you get a GUI!

Have a lot of fun!

''')

if (not args.noclients) and (not args.noui):
    display(NRUI.tab)
